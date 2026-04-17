"""Page-Hinkley change-point detector for upstream data-feed latency
(Layer 3 of the feed-reliability learning loop, spec §14.5 v1.7).

Runs on every scheduled event firing: given an observed
`latency_seconds` (wall-clock arrival − scheduled release, or 0 for
punctual feeds), updates a per-feed running state and trips when
cumulative positive drift exceeds a threshold. Tripping fires a
`data_ingestion_failure` event with `detected_by="page_hinkley"` BEFORE
the scheduler's tolerance-window path would emit one — early warning
for slow-drift failures that don't step-change past tolerance in one
observation.

Page-Hinkley formulation (one-sided, upward drift, baseline=0):

  sum_t = sum_{t-1} + (x_t − δ)
  min_t = min(min_{t-1}, sum_t)
  PH_t  = sum_t − min_t
  trip  iff PH_t > λ

where x_t is `latency_seconds`, δ is allowed drift per observation,
and λ is the detection threshold. With δ ≈ 0 and punctual feeds
(x_t ≈ 0), sum_t stays near zero and never trips. A latency spike
pushes sum_t up while min_t stays behind, so PH_t grows. Gradual
drift across many observations also accumulates until PH_t > λ.

Determinism: given the same input sequence and parameters, PH trips
at the same index. Replay-safe when state is either restored from
persistence or reset to initial.

Resetting: when a `feed_incidents` row is closed (resolution confirmed),
the handler resets `tripped=False` and zeros `cumulative_sum/
min_cumulative` so the next drift episode is detected fresh. This
module does NOT perform the reset itself — that's a persistence
operation invoked by the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import duckdb

from persistence import get_feed_latency_state, upsert_feed_latency_state

PAGE_HINKLEY_DELTA = 0.005
PAGE_HINKLEY_THRESHOLD = 50.0


@dataclass(frozen=True)
class PageHinkleyState:
    """Per-feed Page-Hinkley detector state. Persisted in
    `feed_latency_state`; loaded on each update so the detector
    survives process restarts (spec §14.5 v1.7 replay determinism)."""

    feed_name: str
    cumulative_sum: float
    min_cumulative: float
    n_observations: int
    last_update_ts_utc: datetime | None
    tripped: bool


def initial_state(feed_name: str) -> PageHinkleyState:
    return PageHinkleyState(
        feed_name=feed_name,
        cumulative_sum=0.0,
        min_cumulative=0.0,
        n_observations=0,
        last_update_ts_utc=None,
        tripped=False,
    )


def update_page_hinkley(
    state: PageHinkleyState,
    latency_seconds: float,
    now_utc: datetime,
    *,
    delta: float = PAGE_HINKLEY_DELTA,
    threshold: float = PAGE_HINKLEY_THRESHOLD,
) -> tuple[PageHinkleyState, bool]:
    """One update step. Returns `(new_state, newly_tripped)` where
    `newly_tripped` is True iff the detector crossed the threshold on
    this specific update (False if it was already tripped or still
    below). Callers fire a `data_ingestion_failure` event only on
    `newly_tripped=True` to avoid duplicate firings once tripped.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    if latency_seconds < 0:
        raise ValueError(f"latency_seconds must be non-negative, got {latency_seconds}")

    new_sum = state.cumulative_sum + (latency_seconds - delta)
    new_min = min(state.min_cumulative, new_sum)
    ph_statistic = new_sum - new_min
    will_be_tripped = state.tripped or (ph_statistic > threshold)
    newly_tripped = (not state.tripped) and will_be_tripped
    return (
        PageHinkleyState(
            feed_name=state.feed_name,
            cumulative_sum=new_sum,
            min_cumulative=new_min,
            n_observations=state.n_observations + 1,
            last_update_ts_utc=now_utc,
            tripped=will_be_tripped,
        ),
        newly_tripped,
    )


def load_or_initial(conn: duckdb.DuckDBPyConnection, feed_name: str) -> PageHinkleyState:
    """Restore state from the `feed_latency_state` table; return a
    fresh initial_state if no row exists yet."""
    row = get_feed_latency_state(conn, feed_name)
    if row is None:
        return initial_state(feed_name)
    return PageHinkleyState(
        feed_name=str(row["feed_name"]),
        cumulative_sum=float(row["cumulative_sum"]),
        min_cumulative=float(row["min_cumulative"]),
        n_observations=int(row["n_observations"]),
        last_update_ts_utc=row["last_update_ts_utc"],
        tripped=bool(row["tripped"]),
    )


def persist(conn: duckdb.DuckDBPyConnection, state: PageHinkleyState) -> None:
    """Upsert `state` into the `feed_latency_state` table. Callers
    typically invoke after every update so the detector survives
    restarts."""
    upsert_feed_latency_state(
        conn,
        feed_name=state.feed_name,
        cumulative_sum=state.cumulative_sum,
        min_cumulative=state.min_cumulative,
        n_observations=state.n_observations,
        last_update_ts_utc=state.last_update_ts_utc,
        tripped=state.tripped,
    )


def observe_latency(
    conn: duckdb.DuckDBPyConnection,
    *,
    feed_name: str,
    latency_seconds: float,
    now_utc: datetime,
    delta: float = PAGE_HINKLEY_DELTA,
    threshold: float = PAGE_HINKLEY_THRESHOLD,
) -> tuple[PageHinkleyState, bool]:
    """One-shot: load, update, persist. Returns `(new_state,
    newly_tripped)`. Designed to be called from `scheduler/calendar.py`
    on every event firing.
    """
    current = load_or_initial(conn, feed_name)
    new_state, newly_tripped = update_page_hinkley(
        current,
        latency_seconds,
        now_utc,
        delta=delta,
        threshold=threshold,
    )
    persist(conn, new_state)
    return new_state, newly_tripped


def reset_for_feed(
    conn: duckdb.DuckDBPyConnection,
    feed_name: str,
) -> None:
    """Zero the detector for `feed_name` (cumulative_sum, min, and
    tripped flag reset). Called when a `feed_incidents` row is closed
    so the next drift episode is detected freshly against a clean
    baseline — prevents a residual positive cumulative_sum from
    tripping immediately on the first post-recovery observation.
    """
    upsert_feed_latency_state(
        conn,
        feed_name=feed_name,
        cumulative_sum=0.0,
        min_cumulative=0.0,
        n_observations=0,
        last_update_ts_utc=None,
        tripped=False,
    )
