"""Leave-one-desk-out attribution (spec §9.1).

Signal-space LODO is computable immediately at decision time: for each
desk that contributed to a Decision, recompute the Controller's
position_size with that desk's weighted contribution removed and diff
against the original. The diff is the desk's marginal push on the
decision. It does not require the Print to have landed.

Grading-space LODO (spec §9.1 step 2, "recompute the downstream grading
once the relevant Prints land") is a strictly stronger attribution — it
answers "was the desk's contribution correct?" — and lands in a
follow-up commit on this module.

The table schema (`attribution_lodo`) stores contribution_metric +
metric_name per (decision_id, desk_name), so both variants coexist as
rows with different metric_name values on the same decision.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import duckdb
import numpy as np

from contracts.v1 import AttributionLodo, Decision, Forecast
from persistence.db import (
    get_latest_controller_params,
    get_latest_signal_weights,
    insert_attribution_lodo,
)

LODO_METRIC_POSITION_SIZE_DELTA = "position_size_delta"


def _counterfactual_position_size(
    *,
    weights: list[dict[str, Any]],
    recent_forecasts: dict[tuple[str, str], Forecast],
    k_regime: float,
    pos_limit_regime: float,
    leave_out_desk: str | None,
) -> float:
    """Recompute position_size as §8.2a would, optionally excluding one desk.

    leave_out_desk=None ⇒ full decision (sanity-check path).
    leave_out_desk=d    ⇒ sets desk d's weight contribution to 0 before sum.
    """
    combined_signal = 0.0
    for row in weights:
        desk_name = str(row["desk_name"])
        if desk_name == leave_out_desk:
            continue
        key = (desk_name, str(row["target_variable"]))
        f = recent_forecasts.get(key)
        if f is None:
            continue
        if f.staleness:
            continue
        combined_signal += float(row["weight"]) * float(f.point_estimate)
    raw = k_regime * combined_signal
    return float(np.clip(raw, -pos_limit_regime, pos_limit_regime))


def compute_lodo_signal_space(
    *,
    conn: duckdb.DuckDBPyConnection,
    decision: Decision,
    recent_forecasts: dict[tuple[str, str], Forecast],
    computed_ts_utc: datetime,
) -> list[AttributionLodo]:
    """One AttributionLodo per desk in the decision's regime weight row.

    contribution_metric = decision.position_size - counterfactual_without_desk.
    Positive ⇒ removing the desk would move position_size downward (desk
    was pushing the position long). Negative ⇒ desk was pushing short.
    Magnitude ⇒ influence under the current k_regime / pos_limit_regime.

    Reads weights + params fresh from the DB (not from the Decision's
    provenance), so the caller must ensure the Controller's SignalWeight
    and ControllerParams rows for this regime have not been re-promoted
    between decide() and the LODO call. In replay this is guaranteed by
    the as-of-time query discipline; in live it is guaranteed by the
    research loop's weight-promotion cadence (§8.3).
    """
    weights = get_latest_signal_weights(conn, decision.regime_id)
    params = get_latest_controller_params(conn, decision.regime_id)
    if params is None:
        raise RuntimeError(f"LODO failed: no ControllerParams for regime {decision.regime_id!r}")

    k = float(params["k_regime"])
    lim = float(params["pos_limit_regime"])

    # Sanity: reproduce the original decision from the stored inputs. If
    # the reproduction drifts, the SignalWeight table has been written to
    # since the decision was emitted, which violates the LODO precondition.
    reproduced = _counterfactual_position_size(
        weights=weights,
        recent_forecasts=recent_forecasts,
        k_regime=k,
        pos_limit_regime=lim,
        leave_out_desk=None,
    )
    # Use a tolerance-based check because float comparisons may drift by 1 ULP.
    if not np.isclose(reproduced, decision.position_size, atol=1e-9):
        raise RuntimeError(
            "LODO precondition violated: recomputed position_size "
            f"{reproduced:.12f} ≠ stored {decision.position_size:.12f}; "
            "likely cause is weight or params row mutated between decide() "
            "and compute_lodo."
        )

    rows: list[AttributionLodo] = []
    for row in weights:
        d_name = str(row["desk_name"])
        lodo_size = _counterfactual_position_size(
            weights=weights,
            recent_forecasts=recent_forecasts,
            k_regime=k,
            pos_limit_regime=lim,
            leave_out_desk=d_name,
        )
        delta = decision.position_size - lodo_size
        rows.append(
            AttributionLodo(
                attribution_id=str(uuid.uuid4()),
                decision_id=decision.decision_id,
                desk_name=d_name,
                contribution_metric=float(delta),
                metric_name=LODO_METRIC_POSITION_SIZE_DELTA,
                computed_ts_utc=computed_ts_utc,
            )
        )
    return rows


def persist_lodo_rows(conn: duckdb.DuckDBPyConnection, rows: list[AttributionLodo]) -> None:
    """Convenience wrapper that loops insert_attribution_lodo."""
    for r in rows:
        insert_attribution_lodo(conn, r)
