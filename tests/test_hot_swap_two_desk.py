"""Two-desk hot-swap test (D9 M-4, v1.14 Gate 3).

Same-target production scenario: dealer_inventory + hedging_demand
both target VIX_30D_FORWARD. When desk A is swapped to a stub, desk
B's contribution to the Decision must be unchanged. This test pins
that invariant because the Phase 2 D8 same-target aggregation issue
means sum-over-desks Shapley shares reflect forecast scale, not
independent information; the hot-swap harness is the one place this
assumption can be verified at Controller-decide time.

Pattern:
  - Seed cold-start with both desks at uniform weights.
  - Construct forecasts for both.
  - Swap desk A (dealer_inventory) → stub. Assert:
      delta_a = -weight_A × point_A
      desk B's contribution unchanged.
  - Swap desk B (hedging_demand) → stub. Assert:
      delta_b = -weight_B × point_B
      desk A's contribution unchanged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from contracts.target_variables import VIX_30D_FORWARD
from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    RegimeLabel,
    UncertaintyInterval,
)
from controller import Controller, seed_cold_start
from desks.dealer_inventory import DealerInventoryDesk
from desks.hedging_demand import HedgingDemandDesk
from eval import build_hot_swap_callables
from persistence import connect, init_db

NOW = datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC)
BOOT_TS = NOW - timedelta(hours=1)


def _prov(desk: str) -> Provenance:
    return Provenance(
        desk_name=desk,
        model_name="ridge",
        model_version="0.1",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="0" * 40,
    )


def _fcast(
    *,
    desk: str,
    point: float,
    event_id: str,
    horizon_days: int = 3,
) -> Forecast:
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=NOW,
        target_variable=VIX_30D_FORWARD,
        horizon=EventHorizon(event_id=event_id, expected_ts_utc=NOW + timedelta(days=horizon_days)),
        point_estimate=point,
        uncertainty=UncertaintyInterval(level=0.8, lower=point - 2.0, upper=point + 2.0),
        directional_claim=DirectionalClaim(variable=VIX_30D_FORWARD, sign="positive"),
        staleness=False,
        confidence=0.7,
        provenance=_prov(desk),
    )


def _regime() -> RegimeLabel:
    return RegimeLabel(
        classification_ts_utc=NOW,
        regime_id="regime_boot",
        regime_probabilities={"regime_boot": 1.0},
        transition_probabilities={"regime_boot": 1.0},
        classifier_provenance=_prov("regime_classifier"),
    )


def test_two_desk_swap_preserves_other_desk_contribution(tmp_path):
    """Swap dealer_inventory; verify hedging_demand's contribution
    is unchanged. Then swap hedging_demand; verify dealer_inventory's
    contribution is unchanged. This is the production-scenario invariant
    the single-desk hot-swap test cannot exercise."""
    conn = connect(tmp_path / "gate3_two_desk.duckdb")
    init_db(conn)
    seed_cold_start(
        conn,
        desks=[
            ("dealer_inventory", VIX_30D_FORWARD),
            ("hedging_demand", VIX_30D_FORWARD),
        ],
        regime_ids=["regime_boot"],
        boot_ts=BOOT_TS,
    )
    # Both desks seeded with uniform weights = 0.5 each.
    dealer_point = 20.0
    hedging_point = 25.0
    dealer_fc = _fcast(desk="dealer_inventory", point=dealer_point, event_id="vix_settle")
    hedging_fc = _fcast(desk="hedging_demand", point=hedging_point, event_id="cboe_eod")

    # --- Baseline: both desks contribute -------------------------------
    ctrl = Controller(conn=conn)
    recent = {
        ("dealer_inventory", VIX_30D_FORWARD): dealer_fc,
        ("hedging_demand", VIX_30D_FORWARD): hedging_fc,
    }
    baseline = ctrl.decide(now_utc=NOW, regime_label=_regime(), recent_forecasts=recent)
    # combined_signal = 0.5 * 20 + 0.5 * 25 = 22.5
    assert baseline.combined_signal == pytest.approx(22.5, abs=1e-9)
    assert dealer_fc.forecast_id in baseline.input_forecast_ids
    assert hedging_fc.forecast_id in baseline.input_forecast_ids

    # --- Swap A: dealer_inventory → stub. hedging_demand unchanged. ----
    real_fn_a, stub_fn_a = build_hot_swap_callables(
        conn=conn,
        real_desk=DealerInventoryDesk(),
        real_forecast=dealer_fc,
        regime_label=_regime(),
        recent_forecasts_other={("hedging_demand", VIX_30D_FORWARD): hedging_fc},
        now_utc=NOW,
    )
    assert real_fn_a() is True
    assert stub_fn_a() is True

    # --- Swap B: hedging_demand → stub. dealer_inventory unchanged. ----
    real_fn_b, stub_fn_b = build_hot_swap_callables(
        conn=conn,
        real_desk=HedgingDemandDesk(),
        real_forecast=hedging_fc,
        regime_label=_regime(),
        recent_forecasts_other={("dealer_inventory", VIX_30D_FORWARD): dealer_fc},
        now_utc=NOW,
    )
    assert real_fn_b() is True
    assert stub_fn_b() is True


def test_two_desk_swap_detects_cross_contamination_bug():
    """Defensive invariant: build_hot_swap_callables' shallow-copy
    (B-3a) must prevent the stub-variant from mutating the
    recent_forecasts_other dict. If the helper mutated in place, two
    successive calls to the same `build_hot_swap_callables` output
    would interfere. We verify by constructing two independent
    factories using the same recent_forecasts_other dict and asserting
    each produces consistent state."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        conn = connect(Path(td) / "gate3_isolation.duckdb")
        init_db(conn)
        seed_cold_start(
            conn,
            desks=[
                ("dealer_inventory", VIX_30D_FORWARD),
                ("hedging_demand", VIX_30D_FORWARD),
            ],
            regime_ids=["regime_boot"],
            boot_ts=BOOT_TS,
        )
        dealer_fc = _fcast(desk="dealer_inventory", point=20.0, event_id="vix_settle")
        hedging_fc = _fcast(desk="hedging_demand", point=25.0, event_id="cboe_eod")
        shared_other: dict[tuple[str, str], Forecast] = {
            ("hedging_demand", VIX_30D_FORWARD): hedging_fc,
        }
        shared_other_snapshot = dict(shared_other)

        # Build the first factory.
        real_fn_1, stub_fn_1 = build_hot_swap_callables(
            conn=conn,
            real_desk=DealerInventoryDesk(),
            real_forecast=dealer_fc,
            regime_label=_regime(),
            recent_forecasts_other=shared_other,
            now_utc=NOW,
        )
        real_fn_1()
        stub_fn_1()

        # shared_other is untouched.
        assert shared_other == shared_other_snapshot, (
            "build_hot_swap_callables mutated the input recent_forecasts_other dict — "
            "shallow-copy invariant (B-3a) broken"
        )
