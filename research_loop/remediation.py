"""Research-loop remediation actions (spec §7.2 harmful-case).

Turns event-driven handlers from log-only (v0.1) into
actually-do-something operators (v0.2). Current scope: the harmful
gate-failure auto-retire path.

§7.2 table:
    | Desk harmful | Controller strictly better without the desk
    |              | (pre-registered window, statistical significance)
    |              | → Hard-gate retire

Auto-retire semantics: write a `SignalWeight` row with `weight=0.0`
for the (regime, desk, target) tuple, tagged
`validation_artefact="retire:harmful:<reason>"`. The Controller's
latest-weight read on the next decision picks up the zero weight;
the desk's point_estimate drops out of the combined_signal sum.
This is non-destructive — the desk can later be reinstated by a
human-approved rollback (§8.3 rollback-is-distinct-operation rule).

v0.2 scope limit: auto-retire only fires on `failure_mode` strings
that start with `"harmful:"`. Other gate-failure modes (skill miss,
sign-flip but non-harmful) route to the log-only v0.1 handler path.
Full harmful-case diagnostic (§9.1 LODO harmful-detection threshold)
remains a v0.3 item.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import duckdb

from contracts.v1 import SignalWeight
from persistence import insert_signal_weight

HARMFUL_FAILURE_PREFIX = "harmful:"
RETIRE_ARTEFACT_PREFIX = "retire:harmful:"


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
