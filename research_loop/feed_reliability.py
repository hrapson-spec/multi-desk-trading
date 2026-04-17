"""Rolling failure-rate rules + auto-retirement / reinstatement policy
for upstream data feeds (spec §14.5 v1.7, §7.2 parity).

Layer 2 of the feed-reliability learning loop. Periodic reviews run
the rules below to:

  1. Identify feeds whose rolling failure rate crosses a pre-registered
     threshold → retire every desk that depends on them, in EVERY
     regime where the desk currently holds non-zero weight.
  2. Identify feeds that have had no new failures in a recovery window
     → reinstate the desks via Shapley-proportional promotion, falling
     back to a conservative direct insert when Shapley has no rows.
  3. Enforce a cascading-loss cap: no more than
     `max_retirements_per_7_days` desk-regime pairs may be retired in
     any rolling 7-day wall-clock window. When the cap is hit, the
     review handler logs a `feed_reliability_cap_reached` note and
     defers further retirements to the next tick — exposes the failure
     mode rather than hiding it (the cap is a guard, not a gag).

This module is pure: it reads from persistence but does NOT itself
write to signal_weights (that's `remediation.retire_desk_for_all_regimes`
/ `remediation.reinstate_desk_direct`). Handlers in `handlers.py`
orchestrate the two pieces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import duckdb

from persistence import count_feed_incidents_in_window, get_open_feed_incidents

from .remediation import FEED_UNRELIABLE_PREFIX


@dataclass(frozen=True)
class FeedReliabilityStats:
    """Snapshot of a single feed's recent failure history."""

    feed_name: str
    failure_count_window: int
    last_failure_ts_utc: datetime | None
    currently_open: bool


def compute_feed_failure_rate(
    conn: duckdb.DuckDBPyConnection,
    *,
    feed_name: str,
    lookback_days: int,
    now_utc: datetime,
) -> FeedReliabilityStats:
    """Count incidents for `feed_name` opened in the lookback window
    ending at `now_utc`; report whether an incident is currently open."""
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    start_ts = now_utc - timedelta(days=lookback_days)
    count = count_feed_incidents_in_window(
        conn,
        feed_name=feed_name,
        start_ts=start_ts,
        end_ts=now_utc,
    )
    last_row = conn.execute(
        """
        SELECT opened_ts_utc FROM feed_incidents
        WHERE feed_name = ? AND opened_ts_utc >= ? AND opened_ts_utc <= ?
        ORDER BY opened_ts_utc DESC
        LIMIT 1
        """,
        [feed_name, start_ts, now_utc],
    ).fetchone()
    last_ts = last_row[0] if last_row is not None else None
    currently_open = bool(get_open_feed_incidents(conn, feed_name))
    return FeedReliabilityStats(
        feed_name=feed_name,
        failure_count_window=count,
        last_failure_ts_utc=last_ts,
        currently_open=currently_open,
    )


def feeds_meeting_retirement_criteria(
    conn: duckdb.DuckDBPyConnection,
    *,
    feed_names: list[str],
    lookback_days: int,
    threshold_failures: int,
    now_utc: datetime,
) -> list[FeedReliabilityStats]:
    """Subset of `feed_names` whose rolling failure count reaches or
    exceeds `threshold_failures` AND has an incident currently open.

    The "currently open" filter prevents retiring desks for a feed
    that failed repeatedly in the past but is now healthy — in that
    case, reinstatement is the appropriate path (see
    `feeds_eligible_for_reinstatement`).
    """
    out: list[FeedReliabilityStats] = []
    for feed in feed_names:
        stats = compute_feed_failure_rate(
            conn, feed_name=feed, lookback_days=lookback_days, now_utc=now_utc
        )
        if stats.failure_count_window >= threshold_failures and stats.currently_open:
            out.append(stats)
    return out


def feeds_eligible_for_reinstatement(
    conn: duckdb.DuckDBPyConnection,
    *,
    feed_names: list[str],
    recovery_days: int,
    now_utc: datetime,
) -> list[str]:
    """Feeds that (a) have NO currently-open incident and (b) have had
    no new incidents within the last `recovery_days`.

    Eligibility is a necessary — not sufficient — condition for
    reinstatement. The caller must still verify that at least one desk
    for the feed is currently retired under a FEED_UNRELIABLE_PREFIX
    tag (otherwise there's nothing to reinstate).
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    window_start = now_utc - timedelta(days=recovery_days)
    out: list[str] = []
    for feed in feed_names:
        if get_open_feed_incidents(conn, feed):
            continue
        recent_count = count_feed_incidents_in_window(
            conn,
            feed_name=feed,
            start_ts=window_start,
            end_ts=now_utc,
        )
        if recent_count == 0:
            out.append(feed)
    return out


def count_recent_auto_retirements(
    conn: duckdb.DuckDBPyConnection,
    *,
    prefix: str,
    window_days: int,
    now_utc: datetime,
) -> int:
    """Count distinct (regime_id, desk_name, target_variable) triples
    retired by an auto-remediation action tagged `prefix` within the
    last `window_days`.

    Used by the review handler to enforce a cascading-loss cap: if
    `count_recent_auto_retirements(FEED_UNRELIABLE_PREFIX, 7) >= cap`,
    the handler defers further retirements to the next tick.

    A "retirement" is any SignalWeight row whose validation_artefact
    starts with `prefix` and whose weight is 0.0. Counting distinct
    triples (not rows) avoids double-counting replays of the same
    retirement under idempotency retries.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware")
    window_start = now_utc - timedelta(days=window_days)
    row = conn.execute(
        """
        SELECT count(DISTINCT (regime_id, desk_name, target_variable))
        FROM signal_weights
        WHERE validation_artefact LIKE ? || '%'
          AND weight = 0.0
          AND promotion_ts_utc >= ?
          AND promotion_ts_utc <= ?
        """,
        [prefix, window_start, now_utc],
    ).fetchone()
    return int(row[0]) if row is not None else 0


def active_target_variables_for_desk(
    conn: duckdb.DuckDBPyConnection,
    desk_name: str,
) -> list[str]:
    """Distinct target_variables for which `desk_name` has any non-zero
    latest weight in any regime. Used by the review handler to decide
    which (desk, target) pairs to feed into retire_desk_for_all_regimes.
    """
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT regime_id, target_variable, weight,
                   ROW_NUMBER() OVER (
                       PARTITION BY regime_id, target_variable
                       ORDER BY promotion_ts_utc DESC, weight_id DESC
                   ) AS rn
            FROM signal_weights
            WHERE desk_name = ?
        )
        SELECT DISTINCT target_variable
        FROM ranked
        WHERE rn = 1 AND weight > 0.0
        ORDER BY target_variable
        """,
        [desk_name],
    ).fetchall()
    return [str(r[0]) for r in rows]


def retired_desks_for_feed(
    conn: duckdb.DuckDBPyConnection,
    *,
    feed_name: str,
) -> list[tuple[str, str, str]]:
    """(regime_id, desk_name, target_variable) triples currently retired
    for this feed. "Currently retired" means the latest SignalWeight per
    (regime, desk, target) is zero AND was written under the
    FEED_UNRELIABLE_PREFIX:<feed_name> tag.

    This function is the canonical way to discover which desk-regimes
    are waiting on reinstatement when the feed recovers.
    """
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT regime_id, desk_name, target_variable, weight,
                   validation_artefact,
                   ROW_NUMBER() OVER (
                       PARTITION BY regime_id, desk_name, target_variable
                       ORDER BY promotion_ts_utc DESC, weight_id DESC
                   ) AS rn
            FROM signal_weights
        )
        SELECT regime_id, desk_name, target_variable
        FROM ranked
        WHERE rn = 1
          AND weight = 0.0
          AND validation_artefact = ?
        ORDER BY regime_id, desk_name, target_variable
        """,
        [f"{FEED_UNRELIABLE_PREFIX}{feed_name}"],
    ).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]
