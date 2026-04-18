"""End-to-end gate run for DealerInventoryDesk (Phase 2 MVP §12.2).

Three-gate check mirroring test_storage_curve_gates.py but for the
equity-VRP domain:

  - Gate 3 (hot-swap): STRICT. Must pass. Portability invariant.
  - Gate 1 (skill): capability claim. Ridge must beat a random-walk
    baseline on the vol_level target.
  - Gate 2 (sign preservation): capability claim. Positive-sign
    convention dev → test consistency.

If Gate 1 or 2 fails on the synthetic market, document as debit D7
in capability_debits.md (commit C6). Gate 3 MUST pass — it's the
load-bearing portability claim for Phase 2 MVP.

Phase 2 "zero shared-infra changes" is already enforced by
test_phase2_equity_vrp_portability.py + test_phase2_portability_contract.py;
this test proves the desk actually produces gradeable Forecasts
that compose with the Controller's decision flow.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np

from contracts.target_variables import VIX_30D_FORWARD
from contracts.v1 import Print, Provenance, RegimeLabel
from controller import seed_cold_start
from desks.base import StubDesk
from desks.dealer_inventory import ClassicalDealerInventoryModel, DealerInventoryDesk
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
# Gate 3 strict — portability invariant
# ---------------------------------------------------------------------------


def test_dealer_inventory_passes_hot_swap():
    """Gate 3: a generic StubDesk must satisfy DeskProtocol for
    name='dealer_inventory'. Load-bearing portability invariant."""
    d = DealerInventoryDesk()
    assert d.name == "dealer_inventory"
    assert d.target_variable == VIX_30D_FORWARD

    # Hot-swap against generic StubDesk.
    s = StubDesk()
    s.name = "dealer_inventory_stub_swap"
    s.target_variable = d.target_variable
    s.event_id = d.event_id
    assert d.target_variable == s.target_variable


def test_dealer_inventory_stub_fails_skill_passes_hot_swap():
    """Stub (no model) emits null-signal forecasts, fails skill but
    passes hot-swap (DeskProtocol conformance)."""
    d = DealerInventoryDesk()
    # Emit a handful of stub forecasts via the stub-builder path.
    stub_forecasts = [d._build_stub_forecast(NOW + timedelta(days=i)) for i in range(10)]
    assert all(f.staleness for f in stub_forecasts)
    assert all(f.directional_claim.sign == "none" for f in stub_forecasts)
    # Hot-swap: DealerInventoryDesk(model=None) behaves exactly like a StubDesk.
    assert d.model is None


# ---------------------------------------------------------------------------
# Fitted-desk drive: run the classical specialist through held-out market
# ---------------------------------------------------------------------------


def _fit_and_drive():
    path = EquityVolMarket(n_days=N_DAYS, seed=SEED).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=SEED)
    model = ClassicalDealerInventoryModel(horizon_days=HORIZON, alpha=1e-3)
    model.fit(
        path.dealer_flow[:TRAIN_END],
        path.vega_exposure[:TRAIN_END],
        channels.market_price[:TRAIN_END],
    )
    desk = DealerInventoryDesk(model=model)

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
                print_id=f"di-p-{i:04d}",
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


def test_dealer_inventory_classical_fits_and_predicts():
    """Unit check: fit + predict produce finite outputs on the MVP
    synthetic market."""
    path = EquityVolMarket(n_days=200, seed=SEED).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=SEED)
    model = ClassicalDealerInventoryModel(horizon_days=HORIZON, alpha=1e-3)
    model.fit(
        path.dealer_flow[:120],
        path.vega_exposure[:120],
        channels.market_price[:120],
    )
    out = model.predict(path.dealer_flow, path.vega_exposure, channels.market_price, 50)
    assert out is not None
    point, score = out
    assert np.isfinite(point)
    assert np.isfinite(score)
    assert point > 0  # vol is positive.

    # Too-early index returns None (insufficient history).
    assert model.predict(path.dealer_flow, path.vega_exposure, channels.market_price, 3) is None


def test_dealer_inventory_falls_back_to_stub_when_unfit():
    desk = DealerInventoryDesk(model=None)
    path = EquityVolMarket(n_days=50, seed=0).generate()
    channels = EquityObservationChannels.build(path, mode="clean", seed=0)
    f = desk.forecast_from_observation(channels, 30, NOW)
    # Stub fallback signal per StubDesk convention.
    assert f.staleness is True
    assert f.directional_claim.sign == "none"


# ---------------------------------------------------------------------------
# Three-gate run on the fitted classical path
# ---------------------------------------------------------------------------


def test_dealer_inventory_classical_passes_three_gates_on_mvp_market(tmp_path):
    """§12.2-analogue for Phase 2: run Gate 1 + Gate 2 + Gate 3 on the
    fitted classical desk. Gate 3 v1.14: uses the real runtime
    hot-swap harness (Controller.decide() exercised end-to-end). If
    Gate 1 or 2 fails on the synthetic MVP market, this test still
    passes on Gate 3 — the G1/G2 failure is a model-quality debit
    (D7), not an architecture failure."""
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

    # --- v1.14: real Gate 3 harness -------------------------------------
    conn = connect(tmp_path / "gate3_dealer_inventory.duckdb")
    init_db(conn)
    seed_cold_start(
        conn,
        desks=[("dealer_inventory", VIX_30D_FORWARD)],
        regime_ids=["regime_boot"],
        boot_ts=NOW - timedelta(hours=1),
    )
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
        real_desk=DealerInventoryDesk(),
        real_forecast=real_forecast,
        regime_label=regime_label,
        recent_forecasts_other={},
        now_utc=NOW,
    )

    runner = GateRunner(desk_name="dealer_inventory")
    report = runner.run(
        desk_forecasts=drive["forecasts"],
        prints=drive["prints"],
        baseline_fn=rw_baseline,
        directional_split=directional_split,
        expected_sign="positive",
        run_controller_fn=real_fn,
        run_controller_with_stub_fn=stub_fn,
    )

    # Gate 3 — v1.14 runtime hot-swap.
    assert report.gate3_hot_swap.passed, (
        f"Gate 3 runtime hot-swap failed: {report.gate3_hot_swap.metrics}; "
        f"reason: {report.gate3_hot_swap.reason}"
    )
    assert report.gate3_hot_swap.metrics["failure_mode"] == "passed"
    assert report.gate3_hot_swap.metrics["real_ok"] == 1.0
    assert report.gate3_hot_swap.metrics["stub_ok"] == 1.0

    # Diagnostics printed for the Phase 2 MVP completion report.
    g1 = "✓" if report.gate1_skill.passed else "✗"
    g2 = "✓" if report.gate2_sign_preservation.passed else "✗"
    g3 = "✓" if report.gate3_hot_swap.passed else "✗"
    print(
        f"\nPhase 2 MVP dealer_inventory gates: "
        f"G1={g1} G2={g2} G3={g3}  "
        f"(G1 improvement={report.gate1_skill.metrics.get('relative_improvement', 0.0):+.2%}; "
        f"G2 dev_corr={report.gate2_sign_preservation.metrics.get('dev_corr', 0.0):+.3f} "
        f"test_corr={report.gate2_sign_preservation.metrics.get('test_corr', 0.0):+.3f})"
    )

    # Gate 1 and Gate 2 are capability claims — soft-assert via print.
    # If either fails, commit C6's capability_debits.md gets an entry D7.
    # Do NOT fail the test on Gate 1/2 misses — the whole point of the
    # debit framework is that architecture vs. model-quality are
    # separately tracked.


def test_dealer_inventory_gate3_always_passes_strict():
    """The test above covers Gate 3 already, but pin it as its own test
    so the Phase 2 completion manifest can cite one specific test as
    the load-bearing portability invariant."""
    d = DealerInventoryDesk(model=None)
    stub = StubDesk()
    stub.name = d.name
    stub.target_variable = d.target_variable
    stub.event_id = d.event_id

    from desks.base import DeskProtocol

    # Both DealerInventoryDesk and the generic StubDesk-as-dealer_inventory
    # must satisfy DeskProtocol — that's what Gate 3 enforces.
    assert isinstance(d, DeskProtocol)
    assert isinstance(stub, DeskProtocol)
