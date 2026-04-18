"""Phase C integration test (plan §A — realistic contamination).

Runs the pipeline under the realistic observation mode:
  - Phase B diagonal-dominant AR(1) leakage
  - Shared macro chatter during event regimes
  - Per-desk ingest missingness (NaN days ⇒ desk emits stub)
  - Publication lag per desk

The honest-failure-boundary claim: the architecture must survive —
gates run, Shapley runs, weight promotion runs. Per-regime pass rates
may degrade; partial failures are recorded as capability-claim debits,
not hard test failures.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import Forecast, Print, Provenance, RegimeLabel
from controller import seed_cold_start
from desks.demand import ClassicalDemandModel, DemandDesk
from desks.geopolitics import ClassicalGeopoliticsModel, GeopoliticsDesk
from desks.macro import ClassicalMacroModel, MacroDesk
from desks.storage_curve import ClassicalStorageCurveModel, StorageCurveDesk
from desks.supply import ClassicalSupplyModel, SupplyDesk
from eval import build_hot_swap_callables
from persistence import connect, init_db
from sim.latent_state import LatentMarket, phase_a_config
from sim.observations import ObservationChannels, ObservationConfig

N_DAYS = 1200
TRAIN_END = 700
HELD_OUT_START = TRAIN_END
HORIZON = 3
SEED = 16
NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
DESK_NAMES_ORDERED = (
    "storage_curve",
    "supply",
    "demand",
    "geopolitics",
    "macro",
)


def _fit_desks_on_channels(channels):
    """Fit all 5 desks on a channels object. For Phase C, the channels
    may contain NaN (missingness); fit uses only the training split
    which is still clean up to the staleness rate."""
    market_price = channels.market_price

    # Drop NaN rows from training fit (ridge can't handle NaN X).
    def _clean_slice(arr, end):
        return np.where(np.isnan(arr[:end]), 0.0, arr[:end])

    small_alpha = 1e-4
    sc_model = ClassicalStorageCurveModel(lookback=10, horizon_days=HORIZON, alpha=1.0)
    sc_model.fit(market_price[:TRAIN_END])

    supply_obs = channels.by_desk["supply"].components["supply"]
    supply_level_obs = channels.by_desk["supply"].components["supply_level"]
    supply_model = ClassicalSupplyModel(horizon_days=HORIZON, alpha=small_alpha)
    supply_model.fit(
        _clean_slice(supply_obs, TRAIN_END),
        _clean_slice(supply_level_obs, TRAIN_END),
        market_price[:TRAIN_END],
    )

    demand_obs = channels.by_desk["demand"].components["demand"]
    demand_level_obs = channels.by_desk["demand"].components["demand_level"]
    demand_model = ClassicalDemandModel(horizon_days=HORIZON, alpha=small_alpha)
    demand_model.fit(
        _clean_slice(demand_obs, TRAIN_END),
        _clean_slice(demand_level_obs, TRAIN_END),
        market_price[:TRAIN_END],
    )

    ind_obs = channels.by_desk["geopolitics"].components["event_indicator"]
    int_obs = channels.by_desk["geopolitics"].components["event_intensity"]
    raw_int_obs = channels.by_desk["geopolitics"].components["event_intensity_raw"]
    geo_model = ClassicalGeopoliticsModel(horizon_days=HORIZON, alpha=small_alpha)
    geo_model.fit(
        _clean_slice(ind_obs, TRAIN_END),
        _clean_slice(int_obs, TRAIN_END),
        _clean_slice(raw_int_obs, TRAIN_END),
        market_price[:TRAIN_END],
    )

    xi_obs = channels.by_desk["macro"].components["xi"]
    xi_level_obs = channels.by_desk["macro"].components["xi_level"]
    macro_model = ClassicalMacroModel(horizon_days=HORIZON, alpha=small_alpha)
    macro_model.fit(
        _clean_slice(xi_obs, TRAIN_END),
        _clean_slice(xi_level_obs, TRAIN_END),
        market_price[:TRAIN_END],
    )

    return {
        "storage_curve": StorageCurveDesk(model=sc_model),
        "supply": SupplyDesk(model=supply_model),
        "demand": DemandDesk(model=demand_model),
        "geopolitics": GeopoliticsDesk(model=geo_model),
        "macro": MacroDesk(model=macro_model),
    }


def _emit_forecasts(channels, desks):
    held_out_end = N_DAYS - HORIZON
    per_desk: dict[str, dict] = {}
    for name, desk in desks.items():
        forecasts: list[Forecast] = []
        prints: list[Print] = []
        stubs = 0
        for i in range(HELD_OUT_START, held_out_end):
            ts = NOW + timedelta(days=int(i))
            realised_ts = ts + timedelta(days=HORIZON)
            if name == "storage_curve":
                f = desk.forecast_from_observation(channels, i, ts)
            else:
                f = desk.forecast_from_observation(channels, i, ts)
            if f.staleness:
                stubs += 1
            forecasts.append(f)
            prints.append(
                Print(
                    print_id=f"{name}-{i:04d}",
                    realised_ts_utc=realised_ts,
                    target_variable=WTI_FRONT_MONTH_CLOSE,
                    value=float(channels.market_price[i + HORIZON]),
                )
            )
        per_desk[name] = {"forecasts": forecasts, "prints": prints, "stubs": stubs}
    return per_desk


@pytest.fixture(scope="module")
def phase_c_setup():
    path = LatentMarket(n_days=N_DAYS, seed=SEED, config=phase_a_config()).generate()
    channels = ObservationChannels.build(
        path,
        mode="realistic",
        seed=0,
        config=ObservationConfig(
            leakage_strength=0.10,
            chatter_amplitude=0.05,
        ),
    )
    desks = _fit_desks_on_channels(channels)
    per_desk = _emit_forecasts(channels, desks)
    return {"channels": channels, "desks": desks, "per_desk": per_desk}


def test_phase_c_architecture_survives_contamination(phase_c_setup):
    """Pipeline doesn't crash under realistic contamination. Every desk
    emits Forecasts for every held-out day, possibly with staleness=True
    on ingest-failure days. No exceptions."""
    per_desk = phase_c_setup["per_desk"]
    expected_n = N_DAYS - HORIZON - HELD_OUT_START
    for name in DESK_NAMES_ORDERED:
        assert len(per_desk[name]["forecasts"]) == expected_n, (
            f"{name}: expected {expected_n} forecasts; got {len(per_desk[name]['forecasts'])}"
        )


def test_phase_c_ingest_failures_propagate_to_stale_flag(phase_c_setup):
    """At the configured staleness rates (0.01–0.05 per desk), at least
    one desk has ≥ 2 stub-forecast days in the held-out window."""
    per_desk = phase_c_setup["per_desk"]
    desks_with_stubs = sum(1 for name in DESK_NAMES_ORDERED if per_desk[name]["stubs"] >= 2)
    print("\nPhase C stub counts per desk:")
    for name in DESK_NAMES_ORDERED:
        print(f"  {name}: {per_desk[name]['stubs']} stub forecasts")
    assert desks_with_stubs >= 2, f"expected ≥ 2 desks with staleness; saw {desks_with_stubs}"


def test_phase_c_storage_curve_still_emits_live_forecasts(phase_c_setup):
    """Even under the worst contamination, storage_curve (seeing price
    directly + low staleness prob 0.01) should emit mostly live
    forecasts."""
    stubs = phase_c_setup["per_desk"]["storage_curve"]["stubs"]
    total = len(phase_c_setup["per_desk"]["storage_curve"]["forecasts"])
    assert stubs / total < 0.1, f"storage_curve staleness rate too high: {stubs}/{total}"


def test_phase_c_non_storage_desks_report_gate_outcomes(phase_c_setup, tmp_path):
    """Per-desk gate pass-rate check under realistic contamination. At
    minimum, Gate 3 (hot-swap) still passes for every desk — any
    non-stub desk with a valid Forecast boundary satisfies hot-swap.
    Other gates may fail under contamination (that's the honest
    failure boundary)."""
    from eval import GateRunner
    from eval.data import random_walk_price_baseline

    per_desk = phase_c_setup["per_desk"]
    # Build scores/outcomes for gate 2; gate 1 uses random-walk baseline.
    results = {}
    market_price = phase_c_setup["channels"].market_price
    emission_indices = list(range(HELD_OUT_START, N_DAYS - HORIZON))
    rw = random_walk_price_baseline(prices=market_price, emission_indices=emission_indices)

    phase_c_now = datetime(2026, 1, 1, tzinfo=UTC)
    for name in DESK_NAMES_ORDERED:
        drive = per_desk[name]
        desk_instance = phase_c_setup["desks"][name]
        # Synthetic scores/outcomes (derived from forecast drift vs current price)
        scores = []
        outcomes = []
        for i, f in zip(emission_indices, drive["forecasts"], strict=True):
            if f.staleness:
                continue
            current_price = float(market_price[i - 1])
            future_price = float(market_price[i + HORIZON])
            pred_log_ret = float(np.log(f.point_estimate) - np.log(current_price))
            realised_log_ret = float(np.log(future_price) - np.log(current_price))
            scores.append(pred_log_ret)
            outcomes.append(realised_log_ret)
        half = len(scores) // 2

        # v1.14: Gate 3 harness.
        conn = connect(tmp_path / f"gate3_phase_c_{name}.duckdb")
        init_db(conn)
        seed_cold_start(
            conn,
            desks=[(name, desk_instance.target_variable)],
            regime_ids=["regime_boot"],
            boot_ts=phase_c_now - timedelta(hours=1),
        )
        real_forecast = next(
            (f for f in drive["forecasts"] if not f.staleness),
            drive["forecasts"][0],
        )
        regime_label = RegimeLabel(
            classification_ts_utc=phase_c_now,
            regime_id="regime_boot",
            regime_probabilities={"regime_boot": 1.0},
            transition_probabilities={"regime_boot": 1.0},
            classifier_provenance=Provenance(
                desk_name="regime_classifier",
                model_name="stub",
                model_version="0.0.0",
                input_snapshot_hash="0" * 64,
                spec_hash="0" * 64,
                code_commit="0" * 40,
            ),
        )
        real_fn, stub_fn = build_hot_swap_callables(
            conn=conn,
            real_desk=desk_instance,
            real_forecast=real_forecast,
            regime_label=regime_label,
            recent_forecasts_other={},
            now_utc=phase_c_now,
        )
        try:
            runner = GateRunner(desk_name=name)
            report = runner.run(
                desk_forecasts=drive["forecasts"],
                prints=drive["prints"],
                baseline_fn=rw,
                directional_split=(
                    scores[:half],
                    scores[half:],
                    outcomes[:half],
                    outcomes[half:],
                ),
                expected_sign="positive",
                run_controller_fn=real_fn,
                run_controller_with_stub_fn=stub_fn,
            )
            results[name] = (
                report.gate1_skill.passed,
                report.gate2_sign_preservation.passed,
                report.gate3_hot_swap.passed,
            )
        except Exception as e:  # noqa: BLE001 — diagnostic catch
            print(f"{name} gate run raised: {e!r}")
            results[name] = (False, False, False)

    print("\nPhase C gate results (per desk):")
    for name, r in results.items():
        flags = f"G1={'✓' if r[0] else '✗'} G2={'✓' if r[1] else '✗'} G3={'✓' if r[2] else '✗'}"
        print(f"  {name}: {flags}")

    # Architectural claim: Gate 3 is preserved for every desk that emits
    # anything (hot-swap is an interface check, not a signal check).
    g3_count = sum(r[2] for r in results.values())
    assert g3_count == 5, f"Gate 3 must survive contamination; got {g3_count}/5"
