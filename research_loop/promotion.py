"""Weight-promotion proposer + auto-promoter (spec §8.3).

§8.3 prescribes a three-step adaptation path:

  (3) Research loop proposes a new weight matrix — a candidate.
  (4) Candidate validated against recent held-out data on a
      pre-registered promotion metric.
  (5) If the candidate beats current by a pre-registered margin,
      new SignalWeight rows append with a new promotion_ts_utc.

This module ships the v0.2 shape:
  - propose_weights_from_shapley: turn an attribution_shapley rollup
    into a candidate SignalWeight bundle whose weights are
    proportional to |Shapley value| per desk, normalised to sum to 1.
    Zero-|Shapley| desks drop to weight 0 (Controller excludes them
    next call).
  - promote_weights: writes the candidate rows with a new
    promotion_ts_utc and validation_artefact describing the proposer.

**Capability-claim debit** (explicit): this v0.2 omits the §8.3 step 4
held-out validation and margin-beat check. It promotes Shapley-
proportional weights whenever called. Rationale: signal-space Shapley
is itself a sufficient statistic under the characteristic-function
assumption used by compute_shapley_signal_space; a held-out RMSE
margin check needs Print-grounded grading-space attribution (§9.1
step 2) which lands in a later commit. Until then, the research
loop's promotion path runs under a "Shapley-monotone" promotion
contract and the capability debit is recorded in the promotion row's
validation_artefact.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import duckdb

from contracts.v1 import AttributionShapley, Decision, Forecast, SignalWeight
from persistence.db import (
    get_latest_signal_weights,
    insert_signal_weight,
)

PROMOTION_ARTEFACT_SHAPLEY_V02 = "auto:shapley_proportional_v0.2"
PROMOTION_ARTEFACT_VALIDATED_V03 = "auto:margin_validated_v0.3"


@dataclass
class ValidationResult:
    """Outcome of the §8.3 step-4 held-out margin check."""

    passed: bool
    current_mse: float
    candidate_mse: float
    margin: float
    n_held_out: int

    @property
    def improvement_ratio(self) -> float:
        """1 - candidate_mse/current_mse. Positive = candidate reduces error."""
        if self.current_mse == 0.0:
            return 0.0
        return 1.0 - (self.candidate_mse / self.current_mse)


def propose_weights_from_shapley(
    *,
    shapley_rows: Iterable[AttributionShapley],
    current_weights: list[dict[str, Any]],
    new_promotion_ts_utc: datetime,
    validation_artefact: str = PROMOTION_ARTEFACT_SHAPLEY_V02,
) -> list[SignalWeight]:
    """Build a SignalWeight candidate bundle from a Shapley rollup.

    Weights are proportional to |Shapley value|, normalised to sum to
    1 across all desks in the current weight row. Desks present in
    current_weights but absent from shapley_rows (e.g. freshly-added
    desks mid-week) keep their current weight to avoid silently
    dropping them.

    Args:
        shapley_rows: AttributionShapley rows for ONE regime's review.
        current_weights: Result of get_latest_signal_weights(regime).
            Rows shape: {desk_name, target_variable, weight, ...}.
        new_promotion_ts_utc: promotion_ts_utc for the candidate bundle
            — must be strictly greater than any promotion_ts_utc in
            current_weights for the Controller's read query to pick
            the candidate next.
        validation_artefact: tag written to each SignalWeight row.
    """
    if new_promotion_ts_utc.tzinfo is None:
        raise ValueError("new_promotion_ts_utc must be timezone-aware (§14.8)")

    abs_values = {row.desk_name: abs(row.shapley_value) for row in shapley_rows}
    total_abs = sum(abs_values.values())

    # Build candidate row per current (desk, target) pair.
    proposals: list[SignalWeight] = []
    for row in current_weights:
        desk = str(row["desk_name"])
        target = str(row["target_variable"])
        if desk in abs_values and total_abs > 0.0:
            new_w = abs_values[desk] / total_abs
        elif desk not in abs_values:
            # Not represented in this review — fall back to current weight.
            new_w = float(row["weight"])
        else:
            # Every Shapley value is zero: preserve the uniform prior.
            new_w = float(row["weight"])

        # Regime must come from current_weights so we know the key path.
        # get_latest_signal_weights returns dicts without regime_id; fetch
        # the caller's regime separately below in the integration helper.
        proposals.append(
            SignalWeight(
                weight_id=str(uuid.uuid4()),
                regime_id=str(row.get("regime_id", "regime_boot")),
                desk_name=desk,
                target_variable=target,
                weight=float(new_w),
                promotion_ts_utc=new_promotion_ts_utc,
                validation_artefact=validation_artefact,
            )
        )
    return proposals


def promote_weights(conn: duckdb.DuckDBPyConnection, candidate: list[SignalWeight]) -> None:
    """Append each candidate SignalWeight row. Controller picks it up
    on the next read via the (promotion_ts_utc, weight_id) tie-break."""
    for w in candidate:
        insert_signal_weight(conn, w)


def propose_and_promote_from_shapley(
    *,
    conn: duckdb.DuckDBPyConnection,
    regime_id: str,
    shapley_rows: Iterable[AttributionShapley],
    new_promotion_ts_utc: datetime,
    validation_artefact: str = PROMOTION_ARTEFACT_SHAPLEY_V02,
) -> list[SignalWeight]:
    """One-shot helper used by handlers + tests.

    Reads current weights for regime_id, builds a proposal, writes it.
    Returns the SignalWeight bundle that was written.
    """
    current = get_latest_signal_weights(conn, regime_id)
    # Inject regime_id into each row for propose_weights_from_shapley.
    for r in current:
        r.setdefault("regime_id", regime_id)
    proposal = propose_weights_from_shapley(
        shapley_rows=shapley_rows,
        current_weights=current,
        new_promotion_ts_utc=new_promotion_ts_utc,
        validation_artefact=validation_artefact,
    )
    promote_weights(conn, proposal)
    return proposal


# ---------------------------------------------------------------------------
# v0.3: held-out margin validation before promotion (§8.3 step 4)
# ---------------------------------------------------------------------------


def _windowed_mse(
    *,
    weights: list[dict[str, Any]] | list[SignalWeight],
    held_out_decisions: list[Decision],
    recent_forecasts_by_decision: dict[str, dict[tuple[str, str], Forecast]],
    prints_by_decision: dict[str, float],
) -> float:
    """Mean squared error of the weighted combined_signal against prints
    over the held-out window. Weights can be either the DB-row dicts or
    SignalWeight Pydantic models (duck-typed access)."""

    # Index weights by (desk, target) for fast lookup.
    def _row(row: Any) -> tuple[str, str, float]:
        if isinstance(row, SignalWeight):
            return row.desk_name, row.target_variable, row.weight
        return str(row["desk_name"]), str(row["target_variable"]), float(row["weight"])

    weight_by_key = {(_row(w)[0], _row(w)[1]): _row(w)[2] for w in weights}

    sse = 0.0
    n = 0
    for d in held_out_decisions:
        recent = recent_forecasts_by_decision.get(d.decision_id, {})
        print_value = prints_by_decision.get(d.decision_id)
        if print_value is None:
            continue
        combined = 0.0
        for (desk, target), f in recent.items():
            if f.staleness:
                continue
            w = weight_by_key.get((desk, target), 0.0)
            combined += w * float(f.point_estimate)
        err = combined - print_value
        sse += err * err
        n += 1
    if n == 0:
        return 0.0
    return sse / n


def validate_candidate_vs_current(
    *,
    conn: duckdb.DuckDBPyConnection,
    regime_id: str,
    candidate: list[SignalWeight],
    held_out_decisions: list[Decision],
    recent_forecasts_by_decision: dict[str, dict[tuple[str, str], Forecast]],
    prints_by_decision: dict[str, float],
    margin: float = 0.05,
) -> ValidationResult:
    """Return a ValidationResult describing whether candidate beats
    current by at least `margin` on windowed MSE over the held-out
    set. margin = 0.05 ⇒ candidate MSE must be ≤ 95% of current MSE.

    The "current" weight set is the DB state as of call time — callers
    must invoke this BEFORE promote_weights writes the candidate.
    """
    current = get_latest_signal_weights(conn, regime_id)
    current_mse = _windowed_mse(
        weights=current,
        held_out_decisions=held_out_decisions,
        recent_forecasts_by_decision=recent_forecasts_by_decision,
        prints_by_decision=prints_by_decision,
    )
    candidate_mse = _windowed_mse(
        weights=candidate,
        held_out_decisions=held_out_decisions,
        recent_forecasts_by_decision=recent_forecasts_by_decision,
        prints_by_decision=prints_by_decision,
    )
    n = sum(1 for d in held_out_decisions if d.decision_id in prints_by_decision)
    passed = current_mse > 0.0 and candidate_mse < current_mse * (1.0 - margin) and n >= 1
    return ValidationResult(
        passed=passed,
        current_mse=current_mse,
        candidate_mse=candidate_mse,
        margin=margin,
        n_held_out=n,
    )


def propose_validate_and_promote(
    *,
    conn: duckdb.DuckDBPyConnection,
    regime_id: str,
    shapley_rows: Iterable[AttributionShapley],
    new_promotion_ts_utc: datetime,
    held_out_decisions: list[Decision],
    recent_forecasts_by_decision: dict[str, dict[tuple[str, str], Forecast]],
    prints_by_decision: dict[str, float],
    margin: float = 0.05,
) -> tuple[list[SignalWeight], ValidationResult]:
    """Full §8.3 path: propose → validate → promote only on margin-beat.

    Returns (candidate_rows_if_promoted, ValidationResult). If the
    candidate fails validation, candidate_rows_if_promoted is empty
    (the DB is unchanged) but the ValidationResult carries the metrics
    so the caller can log a capability debit / audit entry.
    """
    current = get_latest_signal_weights(conn, regime_id)
    for r in current:
        r.setdefault("regime_id", regime_id)
    candidate = propose_weights_from_shapley(
        shapley_rows=shapley_rows,
        current_weights=current,
        new_promotion_ts_utc=new_promotion_ts_utc,
        validation_artefact=PROMOTION_ARTEFACT_VALIDATED_V03,
    )
    validation = validate_candidate_vs_current(
        conn=conn,
        regime_id=regime_id,
        candidate=candidate,
        held_out_decisions=held_out_decisions,
        recent_forecasts_by_decision=recent_forecasts_by_decision,
        prints_by_decision=prints_by_decision,
        margin=margin,
    )
    if not validation.passed:
        return [], validation
    promote_weights(conn, candidate)
    return candidate, validation
