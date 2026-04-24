"""Pure B6b decision tick tests."""

from __future__ import annotations

from datetime import timedelta

from v2.contracts import DegradationState
from v2.eval.cost_model import CostScenario
from v2.execution import AdapterParams, ControlLawParams, ExposureState
from v2.paper_live import MarketTickContext, run_decision_tick

from .helpers import CONTRACT_HASH, FAMILY, PREREG_HASH, RELEASE_CALENDAR_VERSION, dt, make_forecast


def _exposure(target: float = 0.0) -> ExposureState:
    return ExposureState(
        state=DegradationState.HEALTHY,
        current_target=target,
        last_valid_target=target,
        ticks_since_valid=0,
    )


def _context(**overrides) -> MarketTickContext:
    decision_ts = overrides.pop("decision_ts", dt())
    forecast = overrides.pop("forecast", make_forecast(decision_ts))
    base = {
        "decision_ts": decision_ts,
        "emitted_ts": overrides.pop("emitted_ts", decision_ts),
        "family": FAMILY,
        "forecasts": overrides.pop("forecasts", [forecast]),
        "price": 75.0,
        "realised_return_since_last_tick": 0.01,
        "market_vol_5d": 0.04,
        "prior_exposure": _exposure(),
        "kill_switch_state": "enabled",
        "contract_hash": CONTRACT_HASH,
        "release_calendar_version": RELEASE_CALENDAR_VERSION,
        "prereg_hash": PREREG_HASH,
    }
    base.update(overrides)
    return MarketTickContext(**base)


def _run(context: MarketTickContext):
    return run_decision_tick(
        context,
        control_params=ControlLawParams(k=1.0),
        adapter_params=AdapterParams(
            reference_risk_5d_usd=100_000.0,
            contract_multiplier_bbl=1_000.0,
        ),
        n_soft=2,
        decay_lambda=0.25,
        ttl=timedelta(days=1),
    )


def test_valid_forecast_emits_non_abstain_decision_and_two_ledger_rows():
    outcome = _run(_context())

    assert outcome.decision.abstain is False
    assert outcome.decision.target_risk_budget == outcome.b_t
    assert outcome.new_exposure.state == DegradationState.HEALTHY
    assert {r.scenario for r in outcome.ledger_records} == {
        CostScenario.OPTIMISTIC,
        CostScenario.PESSIMISTIC,
    }
    assert all(record.decision_id is None for record in outcome.ledger_records)
    assert outcome.target_lots == outcome.ledger_records[0].new_lots


def test_family_abstain_records_decision_abstain_but_holds_effective_exposure():
    decision_ts = dt()
    forecast = make_forecast(
        decision_ts,
        abstain=True,
        abstain_reason="required feature missing",
        calibration_score=0.0,
        data_quality_score=0.0,
    )
    outcome = _run(_context(forecast=forecast, prior_exposure=_exposure(0.5), prior_lots=3))

    assert outcome.decision.abstain is True
    assert outcome.decision.target_risk_budget is None
    assert outcome.decision.degradation_state == DegradationState.SOFT_ABSTAIN
    assert outcome.ledger_records[0].new_target == 0.5
    assert outcome.ledger_records[0].new_lots == outcome.target_lots


def test_ttl_breach_forces_hard_fail_even_with_valid_forecast():
    decision_ts = dt()
    outcome = _run(
        _context(
            decision_ts=decision_ts,
            forecast=make_forecast(decision_ts),
            emitted_ts=decision_ts + timedelta(days=2),
            prior_exposure=_exposure(0.6),
        )
    )

    assert outcome.decision.abstain is True
    assert outcome.decision.abstain_reason == "ttl_breached"
    assert outcome.new_exposure.state == DegradationState.HARD_FAIL
    assert outcome.ledger_records[0].new_target == 0.0


def test_kill_switch_halting_uses_synthetic_abstain_and_force_flat():
    outcome = _run(
        _context(
            forecasts=[],
            kill_switch_state="halted",
            kill_switch_halting=True,
            override_abstain_reason="kill_switch:operator halt",
            prior_exposure=_exposure(0.7),
        )
    )

    assert outcome.decision.abstain is True
    assert outcome.decision.abstain_reason == "kill_switch:operator halt"
    assert outcome.new_exposure.state == DegradationState.HARD_FAIL
    assert outcome.forecast_ids == ()
    assert outcome.ledger_records[0].new_lots == 0
