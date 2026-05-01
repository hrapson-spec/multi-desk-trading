"""Stateful B6b paper-live loop tests."""

from __future__ import annotations

import json
from datetime import timedelta

from v2.eval.cost_model import CostScenario
from v2.execution import AdapterParams, ControlLawParams
from v2.execution.simulator import InternalSimulator
from v2.paper_live import PaperLiveLoop

from .helpers import (
    CODE_COMMIT,
    CONTRACT_HASH,
    FAMILY,
    PREREG_HASH,
    RELEASE_CALENDAR_VERSION,
    dt,
    make_forecast,
)


class _Desk:
    family_id = FAMILY
    desk_id = "desk_a"

    def __init__(self):
        self.calls = 0

    def feature_specs(self):
        return []

    def forecast(
        self,
        view,
        *,
        prereg_hash,
        code_commit,
        contract_hash="",
        release_calendar_version="",
        emitted_ts=None,
    ):
        self.calls += 1
        assert prereg_hash == PREREG_HASH
        assert code_commit == CODE_COMMIT
        assert contract_hash == CONTRACT_HASH
        assert release_calendar_version == RELEASE_CALENDAR_VERSION
        return make_forecast(view.as_of_ts, emitted_ts=emitted_ts)


def test_loop_runs_one_tick_and_persists_decision_ledger_and_snapshot(tmp_path):
    runtime_root = tmp_path / "runtime"
    pit_root = tmp_path / "pit"
    desk = _Desk()
    sim = InternalSimulator.open(runtime_root)
    loop = _loop(pit_root, sim, [desk])
    try:
        outcome = loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        assert desk.calls == 1
        assert outcome.decision.abstain is False
        assert sim.counts() == {"family_decisions": 1, "execution_ledger": 2}
        assert sim.latest_decision(FAMILY)["decision_id"].startswith("dec_")
        assert sim.latest(FAMILY, CostScenario.OPTIMISTIC).new_lots == outcome.target_lots
        assert (runtime_root / "paper_live.duckdb").exists()
        assert (pit_root / "pit.duckdb").exists()
        receipt_path = runtime_root / "snapshots" / "2026-04-22T210000Z" / "receipt.json"
        assert receipt_path.exists()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        assert receipt["runtime_counts"] == {"family_decisions": 1, "execution_ledger": 2}
    finally:
        loop.close()
        sim.close()


def test_fresh_loop_seeds_prior_lots_from_existing_runtime_ledger(tmp_path):
    runtime_root = tmp_path / "runtime"
    pit_root = tmp_path / "pit"
    sim = InternalSimulator.open(runtime_root)
    loop = _loop(pit_root, sim, [_Desk()])
    try:
        first = loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        loop.close()

        later = dt() + timedelta(days=1)
        resumed = _loop(pit_root, sim, [_Desk()])
        try:
            second = resumed.tick(
                decision_ts=later,
                emitted_ts=later,
                price=75.0,
                realised_return_since_last_tick=0.0,
                market_vol_5d=0.04,
            )
            assert second.ledger_records[0].prior_lots == first.target_lots
        finally:
            resumed.close()
    finally:
        sim.close()


def _loop(pit_root, simulator, desks):
    return PaperLiveLoop(
        pit_root=pit_root,
        family=FAMILY,
        desks=desks,
        simulator=simulator,
        control_params=ControlLawParams(k=1.0),
        adapter_params=AdapterParams(
            reference_risk_5d_usd=100_000.0,
            contract_multiplier_bbl=1_000.0,
        ),
        n_soft=2,
        decay_lambda=0.25,
        ttl=timedelta(days=1),
        contract_hash=CONTRACT_HASH,
        release_calendar_version=RELEASE_CALENDAR_VERSION,
        prereg_hash=PREREG_HASH,
        code_commit=CODE_COMMIT,
    )
