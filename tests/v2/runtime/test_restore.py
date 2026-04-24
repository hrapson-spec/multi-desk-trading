"""B8 runtime restore tests."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

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
from v2.runtime import SnapshotRestoreError, restore_runtime_snapshot, verify_snapshot_receipt


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


def test_restore_copies_runtime_rows_through_snapshot_and_verifies_target(tmp_path):
    source, loop = _runtime(tmp_path / "source")
    try:
        first = dt()
        second = dt() + timedelta(days=1)
        loop.tick(
            decision_ts=first,
            emitted_ts=first,
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        loop.tick(
            decision_ts=second,
            emitted_ts=second,
            price=76.0,
            realised_return_since_last_tick=0.0,
            market_vol_5d=0.04,
        )

        report = restore_runtime_snapshot(
            source,
            target_runtime_root=tmp_path / "restored",
            decision_ts=first,
        )

        assert report.ok is True
        assert report.family_decision_rows == 1
        assert report.execution_rows == 2
        assert report.snapshot_dirs_copied == 1
        assert (tmp_path / "restored" / "restore_report.json").exists()

        restored = InternalSimulator.open(tmp_path / "restored")
        try:
            assert restored.counts() == {"family_decisions": 1, "execution_ledger": 2}
            assert verify_snapshot_receipt(restored, decision_ts=first).ok is True
            assert not (tmp_path / "restored" / "snapshots" / "2026-04-23T210000Z").exists()
        finally:
            restored.close()
    finally:
        loop.close()
        source.close()


def test_restore_refuses_non_empty_target_without_overwrite(tmp_path):
    source, loop = _runtime(tmp_path / "source")
    target = tmp_path / "restored"
    target.mkdir()
    (target / "placeholder.txt").write_text("occupied\n", encoding="utf-8")
    try:
        loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )

        with pytest.raises(SnapshotRestoreError, match="not empty"):
            restore_runtime_snapshot(source, target_runtime_root=target, decision_ts=dt())
    finally:
        loop.close()
        source.close()


def test_restore_overwrite_replaces_target(tmp_path):
    source, loop = _runtime(tmp_path / "source")
    target = tmp_path / "restored"
    target.mkdir()
    (target / "placeholder.txt").write_text("occupied\n", encoding="utf-8")
    try:
        loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )

        report = restore_runtime_snapshot(
            source,
            target_runtime_root=target,
            decision_ts=dt(),
            overwrite=True,
        )

        assert report.ok is True
        assert not (target / "placeholder.txt").exists()
        assert (target / "paper_live.duckdb").exists()
    finally:
        loop.close()
        source.close()


def test_restore_refuses_tampered_source_receipt(tmp_path):
    source, loop = _runtime(tmp_path / "source")
    try:
        loop.tick(
            decision_ts=dt(),
            emitted_ts=dt(),
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        receipt_path = tmp_path / "source" / "runtime" / "snapshots" / "2026-04-22T210000Z"
        receipt_path = receipt_path / "receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["code_commit"] = "tampered"
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

        with pytest.raises(SnapshotRestoreError, match="source snapshot verification failed"):
            restore_runtime_snapshot(
                source,
                target_runtime_root=tmp_path / "restored",
                decision_ts=dt(),
            )
    finally:
        loop.close()
        source.close()


def _runtime(root):
    runtime_root = root / "runtime"
    sim = InternalSimulator.open(runtime_root)
    loop = PaperLiveLoop(
        pit_root=root / "pit",
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
