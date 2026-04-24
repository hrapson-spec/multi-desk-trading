"""B6b internal simulator persistence tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from v2.contracts import DecisionUnit, DecisionV2, DegradationState
from v2.eval.cost_model import CostScenario
from v2.execution.simulator import (
    InternalSimulator,
    LedgerRecord,
    RuntimeLedgerConflict,
    content_hash,
)


def _decision() -> DecisionV2:
    decision_ts = datetime(2026, 4, 22, 21, 0, tzinfo=UTC)
    return DecisionV2(
        family="oil_wti_5d",
        decision_ts=decision_ts,
        target_variable="WTI_FRONT_1W_LOG_RETURN",
        target_horizon="5d",
        decision_unit=DecisionUnit.LOG_RETURN,
        instrument_spec="WTI front-month futures under rolling_rule_v1",
        roll_rule_id="rolling_rule_v1",
        target_risk_budget=0.25,
        abstain=False,
        degradation_state=DegradationState.HEALTHY,
        valid_until_ts=decision_ts + timedelta(days=1),
        family_quantile_vector=(-0.08, -0.04, -0.01, 0.008, 0.02, 0.05, 0.09),
        pred_scale=0.02,
        market_vol=0.04,
        regime_posterior={"normal": 1.0},
        contributing_forecast_ids=["fct_a"],
        prereg_hash="sha256:prereg",
        contract_hash="sha256:contract",
    )


def _ledger(decision_id: str | None = None) -> LedgerRecord:
    decision_ts = datetime(2026, 4, 22, 21, 0, tzinfo=UTC)
    return LedgerRecord(
        decision_id=decision_id,
        decision_ts=decision_ts,
        emitted_ts=decision_ts,
        family="oil_wti_5d",
        scenario=CostScenario.OPTIMISTIC,
        prior_target=0.0,
        new_target=0.25,
        prior_lots=0,
        new_lots=8,
        raw_lots=8.33,
        effective_b=0.24,
        price=75.0,
        market_vol_5d=0.04,
        fill_cost=0.5,
        gross_return=0.0,
        net_return=-0.5,
        degradation_state=DegradationState.HEALTHY.value,
        abstain=False,
    )


def test_runtime_store_is_separate_from_pit_store(tmp_path):
    sim = InternalSimulator.open(tmp_path)
    try:
        assert (tmp_path / "paper_live.duckdb").exists()
        assert not (tmp_path / "pit.duckdb").exists()
    finally:
        sim.close()


def test_records_decision_and_tick_with_deterministic_ids(tmp_path):
    sim = InternalSimulator.open(tmp_path)
    try:
        decision = _decision()
        family_hash = content_hash({"family": "oil_wti_5d"})
        dec_record = sim.record_decision(
            decision=decision,
            family_forecast_hash=family_hash,
            forecast_ids=("fct_a",),
            kill_switch_state={"system_state": "enabled"},
            emitted_ts=decision.decision_ts,
        )
        assert dec_record.decision_id.startswith("dec_")

        record = _ledger(decision_id=dec_record.decision_id)
        execution_id = sim.record_tick(record)
        assert execution_id.startswith("exec_")
        assert sim.record_tick(record) == execution_id
        assert sim.counts() == {"family_decisions": 1, "execution_ledger": 1}
        assert sim.latest("oil_wti_5d", CostScenario.OPTIMISTIC).new_lots == 8
    finally:
        sim.close()


def test_duplicate_decision_conflict_is_rejected(tmp_path):
    sim = InternalSimulator.open(tmp_path)
    try:
        decision = _decision()
        sim.record_decision(
            decision=decision,
            family_forecast_hash="abc",
            forecast_ids=("fct_a",),
            kill_switch_state={"system_state": "enabled"},
            emitted_ts=decision.decision_ts,
        )
        changed = decision.model_copy(update={"target_risk_budget": 0.30})
        with pytest.raises(RuntimeLedgerConflict):
            sim.record_decision(
                decision=changed,
                family_forecast_hash="abc",
                forecast_ids=("fct_a",),
                kill_switch_state={"system_state": "enabled"},
                emitted_ts=changed.decision_ts,
            )
    finally:
        sim.close()


def test_duplicate_execution_conflict_is_rejected(tmp_path):
    sim = InternalSimulator.open(tmp_path)
    try:
        decision = _decision()
        dec_record = sim.record_decision(
            decision=decision,
            family_forecast_hash="abc",
            forecast_ids=("fct_a",),
            kill_switch_state={"system_state": "enabled"},
            emitted_ts=decision.decision_ts,
        )
        record = _ledger(decision_id=dec_record.decision_id)
        sim.record_tick(record)
        with pytest.raises(RuntimeLedgerConflict):
            sim.record_tick(replace(record, net_return=-0.75))
    finally:
        sim.close()


def test_snapshot_receipt_is_written(tmp_path):
    sim = InternalSimulator.open(tmp_path)
    try:
        decision_ts = datetime(2026, 4, 22, 21, 0, tzinfo=UTC)
        receipt = sim.write_snapshot_receipt(
            decision_ts=decision_ts,
            decision_id="dec_abc",
            execution_ids=("exec_a", "exec_b"),
            kill_switch_hash="ks",
            code_commit="abcdef0",
            contract_hash="sha256:contract",
        )
        assert receipt.exists()
        assert receipt.with_name("receipt.sha256").exists()
    finally:
        sim.close()
