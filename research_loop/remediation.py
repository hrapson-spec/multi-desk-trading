"""Research-loop remediation actions (spec §7.2 harmful-case + §14.5
feed-unreliable retire/reinstate).

Turns event-driven handlers from log-only (v0.1) into
actually-do-something operators. Current scope:
  - v0.2: harmful gate-failure auto-retire (single regime).
  - v0.3: feed-unreliable retirement across ALL regimes where the
    desk holds a non-zero weight. Parity with §7.2 harmful-case
    semantics: an unreliable desk can't be trusted under any regime.
  - v0.3: direct reinstatement (non-Shapley fallback) when a feed
    has recovered but the desk has no recent Shapley attribution.

§7.2 table:
    | Desk harmful | Controller strictly better without the desk
    |              | (pre-registered window, statistical significance)
    |              | → Hard-gate retire

Auto-retire semantics: write a `SignalWeight` row with `weight=0.0`
for the (regime, desk, target) tuple, tagged
`validation_artefact="retire:harmful:<reason>"` (single-regime path)
or `"retire:feed_unreliable:<feed>"` (all-regimes path). The
Controller's latest-weight read on the next decision picks up the
zero weight; the desk's point_estimate drops out of the
combined_signal sum. Non-destructive — prior weight history
preserved in signal_weights.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import duckdb

from contracts.v1 import SignalWeight
from persistence import insert_signal_weight

HARMFUL_FAILURE_PREFIX = "harmful:"
RETIRE_ARTEFACT_PREFIX = "retire:harmful:"
FEED_UNRELIABLE_PREFIX = "retire:feed_unreliable:"
REINSTATE_PREFIX = "reinstate:feed_recovered:"


def retire_desk_for_regime(
    conn: duckdb.DuckDBPyConnection,
    *,
    regime_id: str,
    desk_name: str,
    target_variable: str,
    reason: str,
    now_utc: datetime,
) -> SignalWeight:
    """Write a zero-weight SignalWeight row for (regime, desk, target).

    Idempotent under the Controller's (promotion_ts_utc DESC, weight_id
    DESC) tie-break — multiple retire writes leave the newest one
    winning, so repeated calls don't corrupt state.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware (spec §14.8)")

    sw = SignalWeight(
        weight_id=str(uuid.uuid4()),
        regime_id=regime_id,
        desk_name=desk_name,
        target_variable=target_variable,
        weight=0.0,
        promotion_ts_utc=now_utc,
        validation_artefact=f"{RETIRE_ARTEFACT_PREFIX}{reason}",
    )
    insert_signal_weight(conn, sw)
    return sw


def is_harmful(failure_mode: str) -> bool:
    """Whether a gate_failure event's failure_mode triggers auto-retire."""
    return failure_mode.startswith(HARMFUL_FAILURE_PREFIX)


def _regimes_with_nonzero_weight(
    conn: duckdb.DuckDBPyConnection,
    *,
    desk_name: str,
    target_variable: str,
) -> list[str]:
    """Regime ids whose LATEST SignalWeight for (desk, target) is > 0.

    Uses the same (promotion_ts_utc DESC, weight_id DESC) tie-break as
    Controller's get_latest_signal_weights, applied per-regime.
    """
    rows = conn.execute(
        """
        WITH ranked AS (
            SELECT
                regime_id, weight,
                ROW_NUMBER() OVER (
                    PARTITION BY regime_id
                    ORDER BY promotion_ts_utc DESC, weight_id DESC
                ) AS rn
            FROM signal_weights
            WHERE desk_name = ? AND target_variable = ?
        )
        SELECT DISTINCT regime_id
        FROM ranked
        WHERE rn = 1 AND weight > 0.0
        ORDER BY regime_id
        """,
        [desk_name, target_variable],
    ).fetchall()
    return [str(r[0]) for r in rows]


def retire_desk_for_all_regimes(
    conn: duckdb.DuckDBPyConnection,
    *,
    desk_name: str,
    target_variable: str,
    reason: str,
    now_utc: datetime,
) -> list[SignalWeight]:
    """Zero-weight SignalWeight rows for (desk, target) in every regime
    where it currently holds a non-zero weight (§14.5 feed-unreliable,
    §7.2 harmful-case parity).

    Tagged `validation_artefact = f"{FEED_UNRELIABLE_PREFIX}{reason}"`;
    reason is typically the feed_name. If the desk has no non-zero
    weights anywhere, returns an empty list (no writes). Callers can
    distinguish "already retired" from "not found" via the returned
    length.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware (spec §14.8)")
    regimes = _regimes_with_nonzero_weight(
        conn, desk_name=desk_name, target_variable=target_variable
    )
    written: list[SignalWeight] = []
    for regime_id in regimes:
        sw = SignalWeight(
            weight_id=str(uuid.uuid4()),
            regime_id=regime_id,
            desk_name=desk_name,
            target_variable=target_variable,
            weight=0.0,
            promotion_ts_utc=now_utc,
            validation_artefact=f"{FEED_UNRELIABLE_PREFIX}{reason}",
        )
        insert_signal_weight(conn, sw)
        written.append(sw)
    return written


def reinstate_desk_direct(
    conn: duckdb.DuckDBPyConnection,
    *,
    regime_id: str,
    desk_name: str,
    target_variable: str,
    weight: float,
    reason: str,
    now_utc: datetime,
) -> SignalWeight:
    """Fallback reinstatement: write a non-zero SignalWeight directly
    when Shapley-proportional promotion can't fire (no recent
    attribution rows for the retired desk).

    Tagged `validation_artefact = f"{REINSTATE_PREFIX}{reason}"`.
    Conservative default for `weight`: 0.1 — non-zero so the Controller
    picks the desk back up, but below a uniform prior so it re-earns
    weight via the next Shapley-based promotion.
    """
    if now_utc.tzinfo is None:
        raise ValueError("now_utc must be timezone-aware (spec §14.8)")
    if weight < 0.0:
        raise ValueError(f"weight must be >= 0.0, got {weight}")
    sw = SignalWeight(
        weight_id=str(uuid.uuid4()),
        regime_id=regime_id,
        desk_name=desk_name,
        target_variable=target_variable,
        weight=weight,
        promotion_ts_utc=now_utc,
        validation_artefact=f"{REINSTATE_PREFIX}{reason}",
    )
    insert_signal_weight(conn, sw)
    return sw
