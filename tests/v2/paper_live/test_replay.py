"""Replay determinism tests for B6b runtime rows."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

from v2.contracts import DegradationState
from v2.execution import AdapterParams, ControlLawParams, ExposureState
from v2.execution.simulator import InternalSimulator, content_hash
from v2.paper_live import MarketTickContext, run_decision_tick

from .helpers import CONTRACT_HASH, FAMILY, PREREG_HASH, RELEASE_CALENDAR_VERSION, dt, make_forecast


def test_replaying_same_tick_is_idempotent_when_hashes_match(tmp_path):
    sim = InternalSimulator.open(tmp_path)
    try:
        outcome = _run()
        first_decision, first_execs = _persist(sim, outcome)

        replay = _run()
        replay_decision, replay_execs = _persist(sim, replay)

        assert replay_decision.decision_id == first_decision.decision_id
        assert replay_execs == first_execs
        assert sim.counts() == {"family_decisions": 1, "execution_ledger": 2}
    finally:
        sim.close()

    fresh_sim = InternalSimulator.open(tmp_path / "fresh")
    try:
        fresh_decision, fresh_execs = _persist(fresh_sim, _run())
        assert fresh_decision.decision_id == first_decision.decision_id
        assert fresh_execs == first_execs
        assert fresh_sim.counts() == {"family_decisions": 1, "execution_ledger": 2}
    finally:
        fresh_sim.close()


def _run():
    decision_ts = dt()
    return run_decision_tick(
        MarketTickContext(
            decision_ts=decision_ts,
            emitted_ts=decision_ts,
            family=FAMILY,
            forecasts=[make_forecast(decision_ts)],
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
            prior_exposure=ExposureState(
                state=DegradationState.HEALTHY,
                current_target=0.0,
                last_valid_target=0.0,
                ticks_since_valid=0,
            ),
            kill_switch_state="enabled",
            contract_hash=CONTRACT_HASH,
            release_calendar_version=RELEASE_CALENDAR_VERSION,
            prereg_hash=PREREG_HASH,
        ),
        control_params=ControlLawParams(k=1.0),
        adapter_params=AdapterParams(
            reference_risk_5d_usd=100_000.0,
            contract_multiplier_bbl=1_000.0,
        ),
        n_soft=2,
        decay_lambda=0.25,
        ttl=timedelta(days=1),
    )


def _persist(sim: InternalSimulator, outcome):
    decision = sim.record_decision(
        decision=outcome.decision,
        family_forecast_hash=content_hash(outcome.family_forecast),
        forecast_ids=outcome.forecast_ids,
        kill_switch_state={"system_state": "enabled"},
        emitted_ts=dt(),
    )
    executions = tuple(
        sim.record_tick(replace(record, decision_id=decision.decision_id))
        for record in outcome.ledger_records
    )
    return decision, executions
