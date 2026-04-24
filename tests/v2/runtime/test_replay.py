"""B7 snapshot receipt replay verification tests."""

from __future__ import annotations

import json
from datetime import timedelta

from tests.v2.paper_live.helpers import (
    CODE_COMMIT,
    CONTRACT_HASH,
    FAMILY,
    PREREG_HASH,
    RELEASE_CALENDAR_VERSION,
    dt,
    make_forecast,
)
from v2.execution import AdapterParams, ControlLawParams
from v2.execution.simulator import InternalSimulator
from v2.paper_live import PaperLiveLoop
from v2.runtime import verify_snapshot_receipt


class _Desk:
    family_id = FAMILY
    desk_id = "desk_a"

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
        return make_forecast(view.as_of_ts, emitted_ts=emitted_ts)


def test_verify_snapshot_receipt_passes_for_loop_receipt(tmp_path):
    sim, loop = _runtime(tmp_path)
    try:
        loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )

        result = verify_snapshot_receipt(sim, decision_ts=dt())

        assert result.ok is True
        assert result.failures == ()
    finally:
        loop.close()
        sim.close()


def test_receipt_tamper_is_detected(tmp_path):
    sim, loop = _runtime(tmp_path)
    try:
        loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        receipt_path = tmp_path / "runtime" / "snapshots" / "2026-04-22T210000Z"
        receipt_path = receipt_path / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["code_commit"] = "tampered"
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        result = verify_snapshot_receipt(sim, decision_ts=dt())

        assert result.ok is False
        assert _failed(result, "receipt.sha256.matches")
    finally:
        loop.close()
        sim.close()


def test_missing_execution_row_is_detected(tmp_path):
    sim, loop = _runtime(tmp_path)
    try:
        loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        receipt_path = tmp_path / "runtime" / "snapshots" / "2026-04-22T210000Z"
        receipt = json.loads((receipt_path / "receipt.json").read_text(encoding="utf-8"))
        missing_execution_id = receipt["execution_ids"][0]
        sim.conn.execute(
            "DELETE FROM execution_ledger WHERE execution_id = ?",
            [missing_execution_id],
        )

        result = verify_snapshot_receipt(sim, decision_ts=dt())

        assert result.ok is False
        assert _failed(result, f"execution.{missing_execution_id}.row_exists")
        assert _failed(result, "runtime_counts.through_snapshot")
    finally:
        loop.close()
        sim.close()


def test_execution_hash_drift_is_detected(tmp_path):
    sim, loop = _runtime(tmp_path)
    try:
        loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        receipt_path = tmp_path / "runtime" / "snapshots" / "2026-04-22T210000Z"
        receipt = json.loads((receipt_path / "receipt.json").read_text(encoding="utf-8"))
        execution_id = receipt["execution_ids"][0]
        sim.conn.execute(
            "UPDATE execution_ledger SET net_return = net_return + 1 WHERE execution_id = ?",
            [execution_id],
        )

        result = verify_snapshot_receipt(sim, decision_ts=dt())

        assert result.ok is False
        assert _failed(result, f"execution.{execution_id}.hash_matches")
    finally:
        loop.close()
        sim.close()


def test_snapshot_counts_are_checked_at_snapshot_time_not_current_time(tmp_path):
    sim, loop = _runtime(tmp_path)
    try:
        loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        later = dt() + timedelta(days=1)
        loop.tick(
            decision_ts=later,
            emitted_ts=later,
            price=76.0,
            realised_return_since_last_tick=0.0,
            market_vol_5d=0.04,
        )

        assert sim.counts() == {"family_decisions": 2, "execution_ledger": 4}
        result = verify_snapshot_receipt(sim, decision_ts=dt())

        assert result.ok is True
    finally:
        loop.close()
        sim.close()


def _runtime(tmp_path):
    runtime_root = tmp_path / "runtime"
    sim = InternalSimulator.open(runtime_root)
    loop = PaperLiveLoop(
        pit_root=tmp_path / "pit",
        family=FAMILY,
        desks=[_Desk()],
        simulator=sim,
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
    return sim, loop


def _failed(result, name: str) -> bool:
    return any(check.name == name and not check.passed for check in result.checks)
