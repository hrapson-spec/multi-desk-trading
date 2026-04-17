"""Research-loop latency KPI aggregation (spec §12.2 point 5).

Every ResearchLoopEvent records a `triggered_at_utc` and (on completion)
a `completed_at_utc`. This module computes the Phase-1 done-criterion
latency statistics over a window:

  - per-event-type latency distribution (mean, p50, p95, max)
  - completion rate (fraction of triggered events that completed)
  - n_events per type

The report is the structured artefact the done-criterion demands —
"research-loop latency KPI measured and reported, not 'pending data'"
per spec §12.2 point 5.

The aggregation reads strictly from the `research_loop_events` table
and does not modify state. Safe to run on a production DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from statistics import mean, median

import duckdb


@dataclass(frozen=True)
class PerTypeLatency:
    """Latency stats for one event type over the window."""

    event_type: str
    n_triggered: int
    n_completed: int
    completion_rate: float  # n_completed / n_triggered
    mean_latency_s: float | None  # None if no completed events
    p50_latency_s: float | None
    p95_latency_s: float | None
    max_latency_s: float | None


@dataclass(frozen=True)
class LatencyReport:
    """Aggregated report across all event types in the window."""

    window_start_ts_utc: datetime
    window_end_ts_utc: datetime
    per_type: dict[str, PerTypeLatency]
    overall_n_triggered: int
    overall_n_completed: int
    overall_completion_rate: float


def _percentile(values: list[float], p: float) -> float:
    """Nearest-rank percentile (p ∈ [0, 100]). values must be non-empty."""
    if not values:
        raise ValueError("percentile on empty list")
    sorted_vals = sorted(values)
    k = int((p / 100.0) * (len(sorted_vals) - 1) + 0.5)
    k = min(max(k, 0), len(sorted_vals) - 1)
    return sorted_vals[k]


def compute_latency_report(
    conn: duckdb.DuckDBPyConnection,
    *,
    window_start_ts_utc: datetime,
    window_end_ts_utc: datetime,
) -> LatencyReport:
    """Compute per-event-type + overall latency statistics over a window.

    Events are included if `triggered_at_utc` is within [start, end].
    Completion rate is computed against triggered events in the window,
    regardless of whether the completion timestamp was inside or after
    the window (a pending event that triggered in-window but hasn't
    completed yet counts as triggered-but-not-completed).
    """
    rows = conn.execute(
        """
        SELECT event_type, triggered_at_utc, completed_at_utc
        FROM research_loop_events
        WHERE triggered_at_utc >= ? AND triggered_at_utc <= ?
        ORDER BY event_type, triggered_at_utc
        """,
        [window_start_ts_utc, window_end_ts_utc],
    ).fetchall()

    by_type: dict[str, list[tuple[datetime, datetime | None]]] = {}
    for r in rows:
        event_type = r[0]
        triggered = r[1]
        completed = r[2]  # may be None for pending events
        by_type.setdefault(event_type, []).append((triggered, completed))

    per_type_report: dict[str, PerTypeLatency] = {}
    total_triggered = 0
    total_completed = 0

    for event_type, items in by_type.items():
        n_triggered = len(items)
        latencies = [(c - t).total_seconds() for (t, c) in items if c is not None]
        n_completed = len(latencies)
        total_triggered += n_triggered
        total_completed += n_completed

        completion_rate = n_completed / n_triggered if n_triggered > 0 else 0.0
        if latencies:
            mean_s: float | None = float(mean(latencies))
            p50_s: float | None = float(median(latencies))
            p95_s: float | None = float(_percentile(latencies, 95.0))
            max_s: float | None = float(max(latencies))
        else:
            mean_s = None
            p50_s = None
            p95_s = None
            max_s = None

        per_type_report[event_type] = PerTypeLatency(
            event_type=event_type,
            n_triggered=n_triggered,
            n_completed=n_completed,
            completion_rate=completion_rate,
            mean_latency_s=mean_s,
            p50_latency_s=p50_s,
            p95_latency_s=p95_s,
            max_latency_s=max_s,
        )

    overall_rate = total_completed / total_triggered if total_triggered > 0 else 0.0
    return LatencyReport(
        window_start_ts_utc=window_start_ts_utc,
        window_end_ts_utc=window_end_ts_utc,
        per_type=per_type_report,
        overall_n_triggered=total_triggered,
        overall_n_completed=total_completed,
        overall_completion_rate=overall_rate,
    )
