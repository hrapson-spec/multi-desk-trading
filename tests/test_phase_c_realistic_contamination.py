"""Phase C integration test (§12.2 Logic gate — realistic contamination).

Runs the pipeline under the realistic observation mode, which combines:
  - Phase B diagonal-dominant AR(1) leakage
  - Shared macro chatter during event regimes
  - Per-desk ingest missingness (NaN days ⇒ desk emits stub with
    staleness=True)
  - Publication lag per desk

Restored at Y3 (2026-04-22) for the v1.16 3-desk oil roster after W6
deletion.

Architectural claim: the pipeline must survive — gates run without
exceptions, hot-swap boundaries hold, staleness propagates. Partial
model-quality failures are recorded as capability-claim debits (Gate
1/Gate 2 may degrade), not hard test failures. Gate 3 (interface
contract, model-independent) must hold 3/3.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import Forecast, Print, Provenance, RegimeLabel
from controller import seed_cold_start
from desks.oil_demand_nowcast import ClassicalOilDemandNowcastModel, OilDemandNowcastDesk
from desks.storage_curve import ClassicalStorageCurveModel, StorageCurveDesk
from desks.supply_disruption_news import (
    ClassicalSupplyDisruptionNewsModel,
    SupplyDisruptionNewsDesk,
)
from eval import GateRunner, build_hot_swap_callables
from eval.data import random_walk_price_baseline, zero_return_baseline
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
    "supply_disruption_news",
    "oil_demand_nowcast",
)


def _clean_slice(arr: np.ndarray, end: int) -> np.ndarray:
    """Drop NaN from the training slice (ridge can't handle NaN X)."""
    return np.where(np.isnan(arr[:end]), 0.0, arr[:end])


def _fit_desks_on_channels(channels):
    """Fit the v1.16 3-desk roster on the contaminated channels. NaN
    entries from ingest-missingness are replaced with 0.0 during
    training (serve-time handles NaN via the desk's staleness path)."""
    market_price = channels.market_price
    small_alpha = 1e-4

    sc_model = ClassicalStorageCurveModel(lookback=10, horizon_days=HORIZON, alpha=1.0)
    sc_model.fit(market_price[:TRAIN_END])

    ind_obs = channels.by_desk["geopolitics"].components["event_indicator"]
    int_obs = channels.by_desk["geopolitics"].components["event_intensity"]
    raw_int_obs = channels.by_desk["geopolitics"].components["event_intensity_raw"]
    sdn_model = ClassicalSupplyDisruptionNewsModel(horizon_days=HORIZON, alpha=small_alpha)
    sdn_model.fit(
        _clean_slice(ind_obs, TRAIN_END),
        _clean_slice(int_obs, TRAIN_END),
        _clean_slice(raw_int_obs, TRAIN_END),
        market_price[:TRAIN_END],
    )

    demand_obs = channels.by_desk["demand"].components["demand"]
    demand_level_obs = channels.by_desk["demand"].components["demand_level"]
    odn_model = ClassicalOilDemandNowcastModel(horizon_days=HORIZON, alpha=small_alpha)
    odn_model.fit(
        _clean_slice(demand_obs, TRAIN_END),
        _clean_slice(demand_level_obs, TRAIN_END),
        market_price[:TRAIN_END],
    )

    return {
        "storage_curve": StorageCurveDesk(model=sc_model),
        "supply_disruption_news": SupplyDisruptionNewsDesk(model=sdn_model),
        "oil_demand_nowcast": OilDemandNowcastDesk(model=odn_model),
    }


def _emit_forecasts(channels, desks):
    """Drive each desk through the held-out slice. Per-desk Print target
    and value mirror the desk's emitted target (price vs log-return) so
    the later gate runner compares like with like."""
    market_price = channels.market_price
    held_out_end = N_DAYS - HORIZON
    per_desk: dict[str, dict] = {}
    for name, desk in desks.items():
        forecasts: list[Forecast] = []
        prints: list[Print] = []
        stubs = 0
        for i in range(HELD_OUT_START, held_out_end):
            ts = NOW + timedelta(days=int(i))
            realised_ts = ts + timedelta(days=HORIZON)
            f = desk.forecast_from_observation(channels, i, ts)
            if f.staleness:
                stubs += 1
            forecasts.append(f)
            target = desk.target_variable
            if target == WTI_FRONT_MONTH_CLOSE:
                print_value = float(market_price[i + HORIZON])
            else:
                print_value = float(
                    np.log(market_price[i + HORIZON]) - np.log(market_price[i - 1])
                )
            prints.append(
                Print(
                    print_id=f"{name}-{i:04d}",
                    realised_ts_utc=realised_ts,
                    target_variable=target,
                    value=print_value,
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
    emits forecasts for every held-out day, possibly with staleness=True
    on ingest-failure days. No exceptions."""
    per_desk = phase_c_setup["per_desk"]
    expected_n = N_DAYS - HORIZON - HELD_OUT_START
    for name in DESK_NAMES_ORDERED:
        assert len(per_desk[name]["forecasts"]) == expected_n, (
            f"{name}: expected {expected_n} forecasts; got {len(per_desk[name]['forecasts'])}"
        )


def test_phase_c_ingest_failures_propagate_to_stale_flag(phase_c_setup):
    """At the configured staleness rates, at least one desk has ≥ 2 stub
    forecasts in the held-out window. v1.16 lowered the "≥ 2 desks"
    threshold to "≥ 1 desk" because the roster shrank 5 → 3 and the
    merged desks read fewer channels (one each) — fewer independent
    staleness sources."""
    per_desk = phase_c_setup["per_desk"]
    desks_with_stubs = sum(1 for name in DESK_NAMES_ORDERED if per_desk[name]["stubs"] >= 2)
    print("\nPhase C stub counts per desk (v1.16):")
    for name in DESK_NAMES_ORDERED:
        print(f"  {name}: {per_desk[name]['stubs']} stub forecasts")
    assert desks_with_stubs >= 1, f"expected ≥ 1 desk with staleness; saw {desks_with_stubs}"


def test_phase_c_storage_curve_still_emits_live_forecasts(phase_c_setup):
    """Even under realistic contamination, storage_curve (seeing price
    directly + low staleness prob 0.01 per the sim config) should emit
    mostly live forecasts — <10% stubs."""
    stubs = phase_c_setup["per_desk"]["storage_curve"]["stubs"]
    total = len(phase_c_setup["per_desk"]["storage_curve"]["forecasts"])
    assert stubs / total < 0.1, f"storage_curve staleness rate too high: {stubs}/{total}"


def test_phase_c_non_storage_desks_report_gate_outcomes(phase_c_setup, tmp_path):
    """Per-desk gate pass-rate check under realistic contamination. The
    load-bearing invariant is Gate 3 (interface contract, model-
    independent) passing 3/3. Gate 1/2 may degrade under contamination
    — recorded as capability debits (D1), not hard failures.

    v1.16: uses per-desk baseline dispatch + per-desk scores/outcomes
    appropriate to the desk's emitted target (log-return for merged
    desks, price-derived log-return for storage_curve)."""
    per_desk = phase_c_setup["per_desk"]
    market_price = phase_c_setup["channels"].market_price
    emission_indices = list(range(HELD_OUT_START, N_DAYS - HORIZON))

    phase_c_now = datetime(2026, 1, 1, tzinfo=UTC)
    results: dict[str, tuple[bool, bool, bool]] = {}
    for name in DESK_NAMES_ORDERED:
        drive = per_desk[name]
        desk_instance = phase_c_setup["desks"][name]

        target = desk_instance.target_variable
        if target == WTI_FRONT_MONTH_CLOSE:
            baseline_fn = random_walk_price_baseline(
                prices=market_price, emission_indices=emission_indices
            )
        else:
            baseline_fn = zero_return_baseline()

        # Per-desk scores / outcomes for Gate 2. For price-target desks,
        # convert point_estimate to a log-return vs current price; for
        # log-return targets, the point_estimate is already the score.
        scores: list[float] = []
        outcomes: list[float] = []
        for i, f in zip(emission_indices, drive["forecasts"], strict=True):
            if f.staleness:
                continue
            current_price = float(market_price[i - 1])
            future_price = float(market_price[i + HORIZON])
            realised_log_ret = float(np.log(future_price) - np.log(current_price))
            if target == WTI_FRONT_MONTH_CLOSE:
                pred_log_ret = float(np.log(f.point_estimate) - np.log(current_price))
            else:
                pred_log_ret = float(f.point_estimate)
            scores.append(pred_log_ret)
            outcomes.append(realised_log_ret)
        half = len(scores) // 2

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
                baseline_fn=baseline_fn,
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

    print("\nPhase C gate results per desk (v1.16):")
    for name, r in results.items():
        flags = f"G1={'✓' if r[0] else '✗'} G2={'✓' if r[1] else '✗'} G3={'✓' if r[2] else '✗'}"
        print(f"  {name}: {flags}")

    # Architectural claim: Gate 3 (interface contract) is preserved for
    # every desk that emits anything — hot-swap is an interface check,
    # not a signal check. Gate 1/2 are capability signals; degradation
    # under contamination is a D1 debit, not a test failure.
    g3_count = sum(r[2] for r in results.values())
    assert g3_count == 3, f"Gate 3 must survive contamination; got {g3_count}/3"
