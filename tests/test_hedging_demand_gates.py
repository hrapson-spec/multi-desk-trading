"""Gate tests for HedgingDemandDesk (Phase 2 scale-out desk 2, v1.13).

Three-gate check mirroring `test_dealer_inventory_gates.py`. Key
differences per the design-review response:

- **Gate 3 language recalibrated** (D9 in capability_debits.md): the
  existing gate harness uses `run_controller_fn=lambda: True` stubs,
  so the runtime hot-swap claim is currently DeskProtocol conformance
  + attribute parity, not a full controller-execution proof. The
  tests below assert what the harness actually verifies, not the
  stronger claim the spec's old language implied.
- **Single-source Gate 3 test** (m-2): one
  `test_hedging_demand_matches_deskprotocol` — no duplicate.
- **Gates 1 + 2 pinned** (m-1): exact metrics recorded on first run
  and asserted within tolerance. Regression signal kicks in if future
  changes silently drift the fitted model.
- **Train/serve on noisy channels** (M-1): fit uses observation
  channels, not clean latent.
- **Sign derivation coverage** (M-3): dedicated test forces a
  negative score and asserts sign="negative".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from contracts.target_variables import VIX_30D_FORWARD
from contracts.v1 import Print, Provenance, RegimeLabel
from controller import seed_cold_start
from desks.base import DeskProtocol, StubDesk
from desks.hedging_demand import ClassicalHedgingDemandModel, HedgingDemandDesk
from eval import GateRunner, build_hot_swap_callables
from eval.data import random_walk_price_baseline
from persistence import connect, init_db
from sim_equity_vrp import EquityObservationChannels, EquityVolMarket

N_DAYS = 1200
TRAIN_END = 700
HELD_OUT_START = TRAIN_END
HORIZON = 3
SEED = 3
NOW = datetime(2026, 4, 18, 10, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Gate 3 — DeskProtocol conformance (the honest claim per D9)
# ---------------------------------------------------------------------------


def test_hedging_demand_matches_deskprotocol():
    """Gate 3 (honest form): HedgingDemandDesk and a generic StubDesk
    configured with the same name/target/event_id both satisfy
    DeskProtocol. This is the portability invariant that the existing
    gate harness actually proves — runtime controller hot-swap is a
    stronger claim tracked as open debit D9."""
    d = HedgingDemandDesk()
    assert d.name == "hedging_demand"
    assert d.target_variable == VIX_30D_FORWARD
    assert isinstance(d, DeskProtocol)

    stub = StubDesk()
    stub.name = d.name
    stub.target_variable = d.target_variable
    stub.event_id = d.event_id
    assert isinstance(stub, DeskProtocol)
    assert stub.target_variable == d.target_variable


# ---------------------------------------------------------------------------
# Stub + fallback behaviour
# ---------------------------------------------------------------------------


def test_hedging_demand_stub_fails_skill_passes_conformance():
    d = HedgingDemandDesk()
    stub_forecasts = [d._build_stub_forecast(NOW + timedelta(days=i)) for i in range(10)]
    assert all(f.staleness for f in stub_forecasts)
    assert all(f.directional_claim.sign == "none" for f in stub_forecasts)
    assert d.model is None


def test_hedging_demand_falls_back_to_stub_when_unfit():
    desk = HedgingDemandDesk(model=None)
    path = EquityVolMarket(n_days=50, seed=0).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=0)
    f = desk.forecast_from_observation(channels, 30, NOW)
    assert f.staleness is True
    assert f.directional_claim.sign == "none"


def test_hedging_demand_classical_fits_and_predicts():
    """Unit check: fit on noisy observation channels, predict finite
    outputs, early-index returns None."""
    path = EquityVolMarket(n_days=200, seed=SEED).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=SEED)
    model = ClassicalHedgingDemandModel(horizon_days=HORIZON, alpha=1e-3)
    hd_obs = channels.by_desk["hedging_demand"].components["hedging_demand_level"]
    skew_obs = channels.by_desk["hedging_demand"].components["put_skew_proxy"]
    model.fit(hd_obs[:120], skew_obs[:120], channels.market_price[:120])
    out = model.predict(hd_obs, skew_obs, channels.market_price, 60)
    assert out is not None
    point, score = out
    assert np.isfinite(point)
    assert np.isfinite(score)
    assert point > 0

    # Too-early index returns None (insufficient history for the lookback).
    assert model.predict(hd_obs, skew_obs, channels.market_price, 3) is None


# ---------------------------------------------------------------------------
# M-3 — sign derivation from score
# ---------------------------------------------------------------------------


def test_hedging_demand_sign_derives_from_score():
    """Force negative, zero, positive ridge outputs by constructing
    a model with known coefficients; assert each emits the correct
    directional_claim.sign."""
    model = ClassicalHedgingDemandModel(horizon_days=HORIZON, alpha=1e-3)
    # Force-fit: directly assign coefficients so predict is a pure function
    # of hd_last. coef[0] controls hd_last contribution; intercept controls
    # baseline.
    model.coef_ = np.array([1.0, 0.0, 0.0, 0.0, 0.0])
    model.intercept_ = 0.0
    model.n_train_ = 100

    # Build a minimal channels-like object with hd_obs + skew_obs + market_price.
    path = EquityVolMarket(n_days=50, seed=0).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=0)
    desk = HedgingDemandDesk(model=model)

    # Manipulate hd_obs array such that at i=20 the last value is very positive,
    # very negative, or zero.
    hd_comp = channels.by_desk["hedging_demand"].components
    hd_comp["hedging_demand_level"][:20] = 0.0
    # Very negative → score < 0 → sign=negative.
    hd_comp["hedging_demand_level"][19] = -10.0
    f = desk.forecast_from_observation(channels, 20, NOW)
    assert f.directional_claim.sign == "negative"

    # Very positive → score > 0 → sign=positive.
    hd_comp["hedging_demand_level"][19] = +10.0
    f = desk.forecast_from_observation(channels, 20, NOW)
    assert f.directional_claim.sign == "positive"

    # Very close to zero → sign=none.
    hd_comp["hedging_demand_level"][19] = 0.0
    # Need the *mean* to dominate; force window to be zero-mean too.
    hd_comp["hedging_demand_level"][:20] = 0.0
    f = desk.forecast_from_observation(channels, 20, NOW)
    assert f.directional_claim.sign == "none"


# ---------------------------------------------------------------------------
# Three-gate run on fitted classical — pinned G1/G2 metrics (m-1 fix)
# ---------------------------------------------------------------------------


def _fit_and_drive():
    path = EquityVolMarket(n_days=N_DAYS, seed=SEED).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=SEED)
    # M-1: fit on NOISY observation channels, not clean latent.
    model = ClassicalHedgingDemandModel(horizon_days=HORIZON, alpha=1e-3)
    hd_obs = channels.by_desk["hedging_demand"].components["hedging_demand_level"]
    skew_obs = channels.by_desk["hedging_demand"].components["put_skew_proxy"]
    model.fit(
        hd_obs[:TRAIN_END],
        skew_obs[:TRAIN_END],
        channels.market_price[:TRAIN_END],
    )
    desk = HedgingDemandDesk(model=model)

    held_out_end = N_DAYS - HORIZON
    forecasts = []
    prints: list[Print] = []
    emission_indices: list[int] = []
    scores: list[float] = []
    outcomes: list[float] = []
    for i in range(HELD_OUT_START, held_out_end):
        emission_ts = NOW + timedelta(days=int(i))
        realised_ts = emission_ts + timedelta(days=HORIZON)
        f = desk.forecast_from_observation(channels, i, emission_ts)
        forecasts.append(f)
        prints.append(
            Print(
                print_id=f"hd-p-{i:04d}",
                realised_ts_utc=realised_ts,
                target_variable=VIX_30D_FORWARD,
                value=float(channels.market_price[i + HORIZON]),
            )
        )
        emission_indices.append(i)
        score = desk.directional_score(channels, i)
        if score is not None:
            scores.append(float(score))
            realised_ret = float(
                np.log(channels.market_price[i + HORIZON]) - np.log(channels.market_price[i - 1])
            )
            outcomes.append(realised_ret)

    return {
        "channels": channels,
        "forecasts": forecasts,
        "prints": prints,
        "emission_indices": emission_indices,
        "scores": scores,
        "outcomes": outcomes,
    }


# ---------------------------------------------------------------------------
# Pinned G1/G2 values — recorded on first run of this test.
# If a future commit drifts them, the assertion fails immediately,
# surfacing the regression. Update only when a deliberate model change
# justifies re-recording.
# ---------------------------------------------------------------------------
# Recorded 2026-04-18 at tag phase2-desk2-hedging-demand-v1.13 (pre-tag run).
# G1 fails Gate 1 threshold (negative improvement vs RW baseline on vol);
# G2 is flat because the ridge emits near-constant scores over the held-out
# window at this config. Both failures expand capability-debit D7 per the
# Phase 2 MVP precedent. Gate 3 passes as DeskProtocol conformance.
_PINNED_G1_RELATIVE_IMPROVEMENT = -0.1060
_PINNED_G2_DEV_CORR = 0.0000
_PINNED_G2_TEST_CORR = 0.0000
_PIN_TOLERANCE = 0.005  # loose enough to absorb float noise, tight enough to catch drift


def test_hedging_demand_classical_three_gates_on_mvp_market(tmp_path):
    """Runs all 3 gates. Gate 3 now uses the v1.14 runtime-harness
    from eval.build_hot_swap_callables — actual Controller.decide()
    execution with Decision validity + combined_signal delta +
    contributing_ids membership assertions. Gates 1+2 pinned to
    recorded values with m-1 tolerance."""
    drive = _fit_and_drive()
    rw_baseline = random_walk_price_baseline(
        prices=drive["channels"].market_price,
        emission_indices=drive["emission_indices"],
    )
    half = len(drive["scores"]) // 2
    directional_split = (
        drive["scores"][:half],
        drive["scores"][half:],
        drive["outcomes"][:half],
        drive["outcomes"][half:],
    )

    # --- v1.14: real Gate 3 harness via build_hot_swap_callables --------
    # Seed a DB and Controller state so the helper can run decide() end-to-end.
    conn = connect(tmp_path / "gate3_hedging.duckdb")
    init_db(conn)
    seed_cold_start(
        conn,
        desks=[("hedging_demand", VIX_30D_FORWARD)],
        regime_ids=["regime_boot"],
        boot_ts=NOW - timedelta(hours=1),
    )
    # Pick a non-stale forecast from the fitted drive. HedgingDemandDesk
    # emits staleness=False when conn is not passed (clean mode).
    real_forecast = next(f for f in drive["forecasts"] if not f.staleness)
    regime_label = RegimeLabel(
        classification_ts_utc=NOW,
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
        real_desk=HedgingDemandDesk(),  # attributes only
        real_forecast=real_forecast,
        regime_label=regime_label,
        recent_forecasts_other={},
        now_utc=NOW,
    )

    runner = GateRunner(desk_name="hedging_demand")
    report = runner.run(
        desk_forecasts=drive["forecasts"],
        prints=drive["prints"],
        baseline_fn=rw_baseline,
        directional_split=directional_split,
        expected_sign="positive",
        run_controller_fn=real_fn,
        run_controller_with_stub_fn=stub_fn,
    )

    # Gate 3 — v1.14 runtime hot-swap (Controller.decide() exercised
    # end-to-end with Decision validity + combined_signal delta +
    # contributing_ids membership assertions via build_hot_swap_callables).
    assert report.gate3_hot_swap.passed, (
        f"Gate 3 runtime hot-swap failed: {report.gate3_hot_swap.metrics}; "
        f"reason: {report.gate3_hot_swap.reason}"
    )
    assert report.gate3_hot_swap.metrics["failure_mode"] == "passed"
    assert report.gate3_hot_swap.metrics["real_ok"] == 1.0
    assert report.gate3_hot_swap.metrics["stub_ok"] == 1.0

    # Gates 1 + 2 pinned metrics (m-1).
    g1_rel_impr = report.gate1_skill.metrics.get("relative_improvement", 0.0)
    g2_dev = report.gate2_sign_preservation.metrics.get("dev_corr", 0.0)
    g2_test = report.gate2_sign_preservation.metrics.get("test_corr", 0.0)

    print(
        f"\nPhase 2 Desk 2 hedging_demand gates: "
        f"G1_rel_impr={g1_rel_impr:+.4f}  "
        f"G2_dev={g2_dev:+.4f}  G2_test={g2_test:+.4f}  "
        f"G3={'✓' if report.gate3_hot_swap.passed else '✗'}"
    )

    assert g1_rel_impr == pytest.approx(_PINNED_G1_RELATIVE_IMPROVEMENT, abs=_PIN_TOLERANCE), (
        f"G1 relative_improvement drifted: {g1_rel_impr:.4f} vs pinned "
        f"{_PINNED_G1_RELATIVE_IMPROVEMENT:.4f}. Update the pin if the change is "
        "deliberate."
    )
    assert g2_dev == pytest.approx(_PINNED_G2_DEV_CORR, abs=_PIN_TOLERANCE), (
        f"G2 dev_corr drifted: {g2_dev:.4f} vs pinned {_PINNED_G2_DEV_CORR:.4f}."
    )
    assert g2_test == pytest.approx(_PINNED_G2_TEST_CORR, abs=_PIN_TOLERANCE), (
        f"G2 test_corr drifted: {g2_test:.4f} vs pinned {_PINNED_G2_TEST_CORR:.4f}."
    )
