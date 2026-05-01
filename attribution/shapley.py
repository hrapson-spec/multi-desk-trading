"""Shapley attribution for Controller decisions (spec §9.2).

Where LODO answers "if this desk were gone, how much worse/better would
the Controller be?", Shapley answers "how much of the signal actually
came from this desk, net of its correlation with every other desk?".
The two are **co-primary** (§9.3).

Phase 1 cadence: weekly during the periodic review, or on demand when a
Controller-commissioned review fires. n ≤ 6 desks ⇒ 2ⁿ = 64 coalitions
per decision, exact. For larger n a sampled variant (100–1000 samples)
will be added as a second function.

Metric families:
  - signal-space: per-desk `position_size_delta` contribution aggregated
    over a window of decisions.
  - grading-space: per-desk `squared_error_reduction` contribution
    aggregated over a window of decisions, using realised Prints.

The window is the review period; the output is one `AttributionShapley`
row per desk with `coalitions_mode="exact"`/`"sampled"` and
`n_decisions` equal to the number of decisions that contributed to the
rollup.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from itertools import combinations
from math import factorial
from typing import Any

import duckdb
import numpy as np

from contracts.v1 import AttributionShapley, Decision, Forecast
from persistence.db import (
    get_latest_controller_params,
    get_latest_signal_weights,
    insert_attribution_shapley,
)

SHAPLEY_METRIC_POSITION_SIZE_DELTA = "position_size_delta"
SHAPLEY_METRIC_SQUARED_ERROR_REDUCTION = "squared_error_reduction"
SHAPLEY_EXACT_MAX_N = 6  # §9.2 cap; beyond this switch to sampled
SHAPLEY_DEFAULT_SAMPLES = 500  # §9.2 "100-1000 samples per decision"


def _coalition_combined_signal(
    *,
    weights: list[dict[str, Any]],
    recent_forecasts: dict[tuple[str, str], Forecast],
    included_desks: frozenset[str],
) -> float:
    """Recompute combined_signal restricted to `included_desks` only."""
    combined_signal = 0.0
    for row in weights:
        d_name = str(row["desk_name"])
        if d_name not in included_desks:
            continue
        key = (d_name, str(row["target_variable"]))
        f = recent_forecasts.get(key)
        if f is None or f.staleness:
            continue
        w = float(row["weight"])
        if w == 0.0:
            continue
        combined_signal += w * float(f.point_estimate)
    return combined_signal


def _coalition_position_size(
    *,
    weights: list[dict[str, Any]],
    recent_forecasts: dict[tuple[str, str], Forecast],
    k_regime: float,
    pos_limit_regime: float,
    included_desks: frozenset[str],
) -> float:
    """Recompute position_size restricted to `included_desks` only."""
    combined_signal = _coalition_combined_signal(
        weights=weights,
        recent_forecasts=recent_forecasts,
        included_desks=included_desks,
    )
    raw = k_regime * combined_signal
    return float(np.clip(raw, -pos_limit_regime, pos_limit_regime))


def _coalition_grading_value(
    *,
    weights: list[dict[str, Any]],
    recent_forecasts: dict[tuple[str, str], Forecast],
    print_value: float,
    included_desks: frozenset[str],
) -> float:
    """Characteristic value for grading-space Shapley.

    v(S) = -(combined_signal(S) - print_value)^2

    This makes the grand-coalition minus empty-coalition total equal the
    realised squared-error reduction over the review window, which is the
    load-bearing quantity for same-target attribution fairness and
    promotion validation.
    """
    combined_signal = _coalition_combined_signal(
        weights=weights,
        recent_forecasts=recent_forecasts,
        included_desks=included_desks,
    )
    err = combined_signal - print_value
    return -(err * err)


def _coalition_normalized_signal(
    *,
    recent_forecasts: dict[tuple[str, str], Forecast],
    included_desks: frozenset[str],
) -> float:
    """Average normalized desk signal over the included coalition.

    Grading-space attribution must compare same-target desks in a unit-free
    contribution space. The normalized forecast values passed in here are
    already z-scored over the review window, so the coalition estimator is the
    mean active normalized signal rather than the raw weighted sum used by the
    live Controller.
    """
    active_values: list[float] = []
    for (desk_name, _target), forecast in recent_forecasts.items():
        if desk_name not in included_desks:
            continue
        if forecast.staleness:
            continue
        active_values.append(float(forecast.point_estimate))
    if not active_values:
        return 0.0
    return float(sum(active_values) / len(active_values))


def _coalition_grading_value_normalized(
    *,
    recent_forecasts: dict[tuple[str, str], Forecast],
    print_value: float,
    included_desks: frozenset[str],
) -> float:
    """Characteristic value on normalized contribution space.

    Both the desk forecasts and the realised print are already z-scored over
    the decision window. This removes same-target level-scale effects, so
    grading-space Shapley reflects information content rather than absolute
    forecast magnitude.
    """
    combined_signal = _coalition_normalized_signal(
        recent_forecasts=recent_forecasts,
        included_desks=included_desks,
    )
    err = combined_signal - print_value
    return -(err * err)


def _shapley_values_for_decision(
    *,
    weights: list[dict[str, Any]],
    recent_forecasts: dict[tuple[str, str], Forecast],
    k_regime: float,
    pos_limit_regime: float,
) -> dict[str, float]:
    """Exact Shapley for a single decision. Returns desk_name → value.

    Characteristic function v(S) = position_size under the coalition of
    desks in S. Shapley(i) = sum_{S ⊆ N\\{i}} |S|! (n-|S|-1)! / n!
                              × [v(S ∪ {i}) − v(S)].
    For n ≤ 6 this is 64 coalition evaluations × n desks = cheap.
    """
    all_desks = [str(row["desk_name"]) for row in weights]
    n = len(all_desks)
    if n == 0:
        return {}
    if n > SHAPLEY_EXACT_MAX_N:
        raise ValueError(
            f"exact Shapley is capped at n={SHAPLEY_EXACT_MAX_N} "
            f"(spec §9.2); got n={n}. Use sampled variant instead."
        )

    # Cache v(S) over all subsets.
    v: dict[frozenset[str], float] = {}
    for r in range(n + 1):
        for subset in combinations(all_desks, r):
            S = frozenset(subset)
            v[S] = _coalition_position_size(
                weights=weights,
                recent_forecasts=recent_forecasts,
                k_regime=k_regime,
                pos_limit_regime=pos_limit_regime,
                included_desks=S,
            )

    n_fact = factorial(n)
    values: dict[str, float] = {}
    for i_name in all_desks:
        acc = 0.0
        others = [d for d in all_desks if d != i_name]
        for r in range(len(others) + 1):
            for subset in combinations(others, r):
                S = frozenset(subset)
                S_with_i = S | {i_name}
                marginal = v[S_with_i] - v[S]
                weight = factorial(len(S)) * factorial(n - len(S) - 1) / n_fact
                acc += weight * marginal
        values[i_name] = acc
    return values


def _shapley_values_for_decision_grading(
    *,
    weights: list[dict[str, Any]],
    recent_forecasts: dict[tuple[str, str], Forecast],
    print_value: float,
) -> dict[str, float]:
    """Exact grading-space Shapley for a single decision.

    Characteristic function:
        v(S) = -(combined_signal(S) - print_value)^2

    Positive Shapley value => on average the desk reduces realised
    squared error across coalitions. Negative => the desk harms realised
    error.
    """
    all_desks = [str(row["desk_name"]) for row in weights]
    n = len(all_desks)
    if n == 0:
        return {}
    if n > SHAPLEY_EXACT_MAX_N:
        raise ValueError(
            f"exact Shapley is capped at n={SHAPLEY_EXACT_MAX_N} "
            f"(spec §9.2); got n={n}. Use sampled variant instead."
        )

    v: dict[frozenset[str], float] = {}
    for r in range(n + 1):
        for subset in combinations(all_desks, r):
            S = frozenset(subset)
            v[S] = _coalition_grading_value(
                weights=weights,
                recent_forecasts=recent_forecasts,
                print_value=print_value,
                included_desks=S,
            )

    n_fact = factorial(n)
    values: dict[str, float] = {}
    for i_name in all_desks:
        acc = 0.0
        others = [d for d in all_desks if d != i_name]
        for r in range(len(others) + 1):
            for subset in combinations(others, r):
                S = frozenset(subset)
                S_with_i = S | {i_name}
                marginal = v[S_with_i] - v[S]
                weight = factorial(len(S)) * factorial(n - len(S) - 1) / n_fact
                acc += weight * marginal
        values[i_name] = acc
    return values


def _shapley_values_for_decision_grading_normalized(
    *,
    desk_names: Sequence[str],
    recent_forecasts: dict[tuple[str, str], Forecast],
    print_value: float,
) -> dict[str, float]:
    """Exact grading-space Shapley on normalized contribution space."""
    all_desks = list(desk_names)
    n = len(all_desks)
    if n == 0:
        return {}
    if n > SHAPLEY_EXACT_MAX_N:
        raise ValueError(
            f"exact Shapley is capped at n={SHAPLEY_EXACT_MAX_N} "
            f"(spec §9.2); got n={n}. Use sampled variant instead."
        )

    v: dict[frozenset[str], float] = {}
    for r in range(n + 1):
        for subset in combinations(all_desks, r):
            S = frozenset(subset)
            v[S] = _coalition_grading_value_normalized(
                recent_forecasts=recent_forecasts,
                print_value=print_value,
                included_desks=S,
            )

    n_fact = factorial(n)
    values: dict[str, float] = {}
    for i_name in all_desks:
        acc = 0.0
        others = [d for d in all_desks if d != i_name]
        for r in range(len(others) + 1):
            for subset in combinations(others, r):
                S = frozenset(subset)
                S_with_i = S | {i_name}
                marginal = v[S_with_i] - v[S]
                weight = factorial(len(S)) * factorial(n - len(S) - 1) / n_fact
                acc += weight * marginal
        values[i_name] = acc
    return values


def _shapley_values_for_decision_sampled(
    *,
    weights: list[dict[str, Any]],
    recent_forecasts: dict[tuple[str, str], Forecast],
    k_regime: float,
    pos_limit_regime: float,
    n_samples: int,
    seed: int,
) -> dict[str, float]:
    """Monte-Carlo Shapley via random permutation sampling.

    For each sampled permutation π of desks, walk left-to-right and
    attribute the marginal v(π[:i+1]) − v(π[:i]) to desk π[i]. Average
    across samples gives an unbiased estimator of the Shapley value.

    n_samples governs variance; §9.2 recommends 100–1000. Seed is
    forwarded so tests can assert determinism (spec §3.1 replay).
    """
    all_desks = [str(row["desk_name"]) for row in weights]
    n = len(all_desks)
    if n == 0:
        return {}
    if n_samples <= 0:
        raise ValueError(f"n_samples must be positive; got {n_samples}")

    import random

    rng = random.Random(seed)

    totals: dict[str, float] = dict.fromkeys(all_desks, 0.0)
    for _ in range(n_samples):
        perm = all_desks[:]
        rng.shuffle(perm)
        # v(empty) = 0 (no contributors)
        prev = 0.0
        current_coalition: set[str] = set()
        for d_name in perm:
            current_coalition.add(d_name)
            cur = _coalition_position_size(
                weights=weights,
                recent_forecasts=recent_forecasts,
                k_regime=k_regime,
                pos_limit_regime=pos_limit_regime,
                included_desks=frozenset(current_coalition),
            )
            totals[d_name] += cur - prev
            prev = cur

    return {d: totals[d] / n_samples for d in all_desks}


def _shapley_values_for_decision_grading_sampled(
    *,
    weights: list[dict[str, Any]],
    recent_forecasts: dict[tuple[str, str], Forecast],
    print_value: float,
    n_samples: int,
    seed: int,
) -> dict[str, float]:
    """Monte-Carlo grading-space Shapley via permutation sampling."""
    all_desks = [str(row["desk_name"]) for row in weights]
    n = len(all_desks)
    if n == 0:
        return {}
    if n_samples <= 0:
        raise ValueError(f"n_samples must be positive; got {n_samples}")

    import random

    rng = random.Random(seed)
    totals: dict[str, float] = dict.fromkeys(all_desks, 0.0)
    for _ in range(n_samples):
        perm = all_desks[:]
        rng.shuffle(perm)
        prev = -(print_value * print_value)
        current_coalition: set[str] = set()
        for d_name in perm:
            current_coalition.add(d_name)
            cur = _coalition_grading_value(
                weights=weights,
                recent_forecasts=recent_forecasts,
                print_value=print_value,
                included_desks=frozenset(current_coalition),
            )
            totals[d_name] += cur - prev
            prev = cur

    return {d: totals[d] / n_samples for d in all_desks}


def _shapley_values_for_decision_grading_normalized_sampled(
    *,
    desk_names: Sequence[str],
    recent_forecasts: dict[tuple[str, str], Forecast],
    print_value: float,
    n_samples: int,
    seed: int,
) -> dict[str, float]:
    """Monte-Carlo grading-space Shapley on normalized contribution space."""
    all_desks = list(desk_names)
    n = len(all_desks)
    if n == 0:
        return {}
    if n_samples <= 0:
        raise ValueError(f"n_samples must be positive; got {n_samples}")

    import random

    rng = random.Random(seed)
    totals: dict[str, float] = dict.fromkeys(all_desks, 0.0)
    empty_value = -(print_value * print_value)
    for _ in range(n_samples):
        perm = all_desks[:]
        rng.shuffle(perm)
        prev = empty_value
        current_coalition: set[str] = set()
        for d_name in perm:
            current_coalition.add(d_name)
            cur = _coalition_grading_value_normalized(
                recent_forecasts=recent_forecasts,
                print_value=print_value,
                included_desks=frozenset(current_coalition),
            )
            totals[d_name] += cur - prev
            prev = cur

    return {d: totals[d] / n_samples for d in all_desks}


def _safe_zscore(value: float, mean: float, std: float) -> float:
    """Return a stable z-score, collapsing zero-variance series to 0."""
    if std <= 0.0:
        return 0.0
    return (value - mean) / std


def _normalized_grading_inputs(
    *,
    decisions: Sequence[Decision],
    recent_forecasts_by_decision: dict[str, dict[tuple[str, str], Forecast]],
    prints_by_decision: dict[str, float],
) -> tuple[dict[str, dict[tuple[str, str], Forecast]], dict[str, float]]:
    """Project raw forecast levels into review-window z-score space.

    D8 root cause: raw-level coalitions make same-target grading-space
    attribution reward forecast scale rather than information content. This
    helper standardizes each desk's forecast history and the realised print
    history over the review window so downstream coalitions operate on a
    unit-free contribution space.
    """
    forecast_series_by_key: dict[tuple[str, str], list[float]] = {}
    print_series_by_target: dict[str, list[float]] = {}

    for decision in decisions:
        print_value = prints_by_decision.get(decision.decision_id)
        if print_value is None:
            continue
        recent = recent_forecasts_by_decision.get(decision.decision_id, {})
        active_targets = {
            forecast.target_variable
            for forecast in recent.values()
            if not forecast.staleness
        }
        if len(active_targets) == 1:
            target = next(iter(active_targets))
            print_series_by_target.setdefault(target, []).append(float(print_value))
        for key, forecast in recent.items():
            if forecast.staleness:
                continue
            forecast_series_by_key.setdefault(key, []).append(float(forecast.point_estimate))

    forecast_stats = {
        key: (float(np.mean(series)), float(np.std(series)))
        for key, series in forecast_series_by_key.items()
    }
    print_stats = {
        target: (float(np.mean(series)), float(np.std(series)))
        for target, series in print_series_by_target.items()
    }

    normalized_recent_by_decision: dict[str, dict[tuple[str, str], Forecast]] = {}
    normalized_prints_by_decision: dict[str, float] = {}
    for decision in decisions:
        raw_print = prints_by_decision.get(decision.decision_id)
        recent = recent_forecasts_by_decision.get(decision.decision_id, {})
        normalized_recent: dict[tuple[str, str], Forecast] = {}
        active_targets = {
            forecast.target_variable
            for forecast in recent.values()
            if not forecast.staleness
        }
        for key, forecast in recent.items():
            if forecast.staleness:
                normalized_recent[key] = forecast
                continue
            mean, std = forecast_stats.get(key, (float(forecast.point_estimate), 0.0))
            normalized_recent[key] = forecast.model_copy(
                update={
                    "point_estimate": float(
                        _safe_zscore(float(forecast.point_estimate), mean, std)
                    )
                }
            )
        normalized_recent_by_decision[decision.decision_id] = normalized_recent

        if raw_print is None or len(active_targets) != 1:
            continue
        target = next(iter(active_targets))
        mean, std = print_stats.get(target, (float(raw_print), 0.0))
        normalized_prints_by_decision[decision.decision_id] = float(
            _safe_zscore(float(raw_print), mean, std)
        )

    return normalized_recent_by_decision, normalized_prints_by_decision


def compute_shapley_signal_space(
    *,
    conn: duckdb.DuckDBPyConnection,
    decisions: Sequence[Decision],
    recent_forecasts_by_decision: dict[str, dict[tuple[str, str], Forecast]],
    review_ts_utc: datetime,
    mode: str = "auto",
    n_samples: int = SHAPLEY_DEFAULT_SAMPLES,
    seed: int = 0,
) -> list[AttributionShapley]:
    """Aggregate Shapley values over the decision window.

    Args:
        conn: DuckDB connection. Used to pull SignalWeights/ControllerParams
            per decision.regime_id. Caller is responsible for ensuring the
            weight rows used at each decision-time have not been mutated —
            same precondition as compute_lodo_signal_space.
        decisions: The decisions inside the review window. All must share
            the same set of (desk_name, target_variable) in their regime
            weight row (no cross-regime aggregation in v0.1; regime-specific
            Shapley rolls up at the research-loop level).
        recent_forecasts_by_decision: Mapping decision_id → the forecast
            dict that fed that decision.
        review_ts_utc: The review period's anchor timestamp (end of week
            for weekly cadence).
        mode: "exact" (requires n ≤ SHAPLEY_EXACT_MAX_N), "sampled", or
            "auto" (exact if n ≤ cap else sampled).
        n_samples: Monte-Carlo sample count per decision when mode="sampled".
        seed: Base seed for sampled mode; the per-decision seed is this
            plus the decision's emission index to decorrelate across
            decisions while preserving replay determinism.

    Returns one AttributionShapley per desk, aggregated across the window
    via average of per-decision Shapley values. coalitions_mode reflects
    whichever path was taken (exact vs sampled) for the first decision's
    n; mixed-mode windows across regime boundaries are not supported in
    v0.1 (all decisions in the window should carry the same n).
    """
    if mode not in ("exact", "sampled", "auto"):
        raise ValueError(f"mode must be exact/sampled/auto; got {mode!r}")
    if not decisions:
        return []

    per_desk_totals: dict[str, float] = {}
    per_desk_n: dict[str, int] = {}
    coalitions_mode: str = "exact"

    for idx, d in enumerate(decisions):
        weights = get_latest_signal_weights(conn, d.regime_id)
        params = get_latest_controller_params(conn, d.regime_id)
        if params is None:
            raise RuntimeError(f"Shapley failed: no ControllerParams for regime {d.regime_id!r}")
        recent = recent_forecasts_by_decision.get(d.decision_id, {})
        n_desks = len(weights)

        use_sampled = mode == "sampled" or (mode == "auto" and n_desks > SHAPLEY_EXACT_MAX_N)
        if use_sampled:
            values = _shapley_values_for_decision_sampled(
                weights=weights,
                recent_forecasts=recent,
                k_regime=float(params["k_regime"]),
                pos_limit_regime=float(params["pos_limit_regime"]),
                n_samples=n_samples,
                seed=seed + idx,
            )
            coalitions_mode = "sampled"
        else:
            values = _shapley_values_for_decision(
                weights=weights,
                recent_forecasts=recent,
                k_regime=float(params["k_regime"]),
                pos_limit_regime=float(params["pos_limit_regime"]),
            )
            # Only mark "exact" if we haven't already seen a sampled row.
            if coalitions_mode == "exact":
                coalitions_mode = "exact"

        for name, val in values.items():
            per_desk_totals[name] = per_desk_totals.get(name, 0.0) + val
            per_desk_n[name] = per_desk_n.get(name, 0) + 1

    rows: list[AttributionShapley] = []
    for name, total in per_desk_totals.items():
        n = per_desk_n.get(name, 1)
        avg = total / n
        rows.append(
            AttributionShapley(
                attribution_id=str(uuid.uuid4()),
                review_ts_utc=review_ts_utc,
                desk_name=name,
                shapley_value=float(avg),
                metric_name=SHAPLEY_METRIC_POSITION_SIZE_DELTA,
                n_decisions=n,
                coalitions_mode=coalitions_mode,  # type: ignore[arg-type]
            )
        )
    return rows


def compute_shapley_grading_space(
    *,
    conn: duckdb.DuckDBPyConnection,
    decisions: Sequence[Decision],
    recent_forecasts_by_decision: dict[str, dict[tuple[str, str], Forecast]],
    prints_by_decision: dict[str, float],
    review_ts_utc: datetime,
    mode: str = "auto",
    n_samples: int = SHAPLEY_DEFAULT_SAMPLES,
    seed: int = 0,
) -> list[AttributionShapley]:
    """Aggregate grading-space Shapley over the decision window.

    Decisions without a realised Print in `prints_by_decision` are skipped.
    The characteristic function operates on z-scored forecast / print series
    over the review window, so same-target desks are compared in a unit-free
    contribution space instead of raw level scale.
    """
    if mode not in ("exact", "sampled", "auto"):
        raise ValueError(f"mode must be exact/sampled/auto; got {mode!r}")
    if not decisions:
        return []

    normalized_recent_by_decision, normalized_prints_by_decision = _normalized_grading_inputs(
        decisions=decisions,
        recent_forecasts_by_decision=recent_forecasts_by_decision,
        prints_by_decision=prints_by_decision,
    )

    per_desk_totals: dict[str, float] = {}
    per_desk_n: dict[str, int] = {}
    coalitions_mode: str = "exact"

    for idx, d in enumerate(decisions):
        print_value = normalized_prints_by_decision.get(d.decision_id)
        if print_value is None:
            continue
        weights = get_latest_signal_weights(conn, d.regime_id)
        desk_names = [str(row["desk_name"]) for row in weights]
        recent = normalized_recent_by_decision.get(d.decision_id, {})
        n_desks = len(weights)

        use_sampled = mode == "sampled" or (mode == "auto" and n_desks > SHAPLEY_EXACT_MAX_N)
        if use_sampled:
            values = _shapley_values_for_decision_grading_normalized_sampled(
                desk_names=desk_names,
                recent_forecasts=recent,
                print_value=float(print_value),
                n_samples=n_samples,
                seed=seed + idx,
            )
            coalitions_mode = "sampled"
        else:
            values = _shapley_values_for_decision_grading_normalized(
                desk_names=desk_names,
                recent_forecasts=recent,
                print_value=float(print_value),
            )
            if coalitions_mode == "exact":
                coalitions_mode = "exact"

        for name, val in values.items():
            per_desk_totals[name] = per_desk_totals.get(name, 0.0) + val
            per_desk_n[name] = per_desk_n.get(name, 0) + 1

    rows: list[AttributionShapley] = []
    for name, total in per_desk_totals.items():
        n = per_desk_n.get(name, 1)
        rows.append(
            AttributionShapley(
                attribution_id=str(uuid.uuid4()),
                review_ts_utc=review_ts_utc,
                desk_name=name,
                shapley_value=float(total / n),
                metric_name=SHAPLEY_METRIC_SQUARED_ERROR_REDUCTION,
                n_decisions=n,
                coalitions_mode=coalitions_mode,  # type: ignore[arg-type]
            )
        )
    return rows


def persist_shapley_rows(conn: duckdb.DuckDBPyConnection, rows: list[AttributionShapley]) -> None:
    for r in rows:
        insert_attribution_shapley(conn, r)
