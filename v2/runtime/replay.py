"""Replay and snapshot receipt verification for v2 runtime state.

B7 verifies the lightweight B6b snapshot receipts. It does not restore
state or mutate runtime tables; it only proves the receipt, runtime DB,
and deterministic hashes still agree.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.eval.cost_model import CostScenario
from v2.execution.simulator import (
    InternalSimulator,
    LedgerRecord,
    execution_hash_for,
)


@dataclass(frozen=True)
class ReplayCheck:
    name: str
    passed: bool
    expected: object | None = None
    actual: object | None = None
    detail: str | None = None


@dataclass(frozen=True)
class SnapshotVerification:
    receipt_path: Path
    receipt: dict[str, Any] | None
    checks: tuple[ReplayCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def failures(self) -> tuple[ReplayCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


def verify_snapshot_receipt(
    simulator: InternalSimulator,
    *,
    decision_ts: datetime | None = None,
    receipt_path: Path | None = None,
) -> SnapshotVerification:
    """Verify a B6b receipt against the runtime DB.

    Pass either `receipt_path` directly or `decision_ts`, which resolves
    to `runtime_root/snapshots/<decision_ts>/receipt.json`.
    """
    if receipt_path is None:
        if decision_ts is None:
            raise ValueError("decision_ts or receipt_path is required")
        receipt_path = simulator.runtime_root / "snapshots" / _timestamp_key(decision_ts)
        receipt_path = receipt_path / "receipt.json"
    receipt_path = Path(receipt_path)

    checks: list[ReplayCheck] = []
    receipt = _read_receipt(receipt_path, checks)
    if receipt is None:
        return SnapshotVerification(receipt_path=receipt_path, receipt=None, checks=tuple(checks))

    _verify_receipt_hash(receipt_path, checks)
    decision_row = _verify_decision(simulator, receipt, checks)
    _verify_executions(simulator, receipt, checks)
    if decision_row is not None:
        _verify_snapshot_counts(simulator, receipt, decision_row["decision_ts"], checks)

    return SnapshotVerification(receipt_path=receipt_path, receipt=receipt, checks=tuple(checks))


def _read_receipt(path: Path, checks: list[ReplayCheck]) -> dict[str, Any] | None:
    if not path.exists():
        checks.append(ReplayCheck("receipt.exists", False, detail=f"{path} is missing"))
        return None
    checks.append(ReplayCheck("receipt.exists", True))
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        checks.append(ReplayCheck("receipt.valid_json", False, detail=str(exc)))
        return None
    checks.append(ReplayCheck("receipt.valid_json", True))
    return receipt


def _verify_receipt_hash(path: Path, checks: list[ReplayCheck]) -> None:
    hash_path = path.with_name("receipt.sha256")
    if not hash_path.exists():
        checks.append(
            ReplayCheck("receipt.sha256.exists", False, detail=f"{hash_path} is missing")
        )
        return
    checks.append(ReplayCheck("receipt.sha256.exists", True))
    receipt_json = path.read_text(encoding="utf-8").strip()
    expected = hash_path.read_text(encoding="utf-8").strip()
    actual = _sha256_hex(receipt_json)
    checks.append(ReplayCheck("receipt.sha256.matches", expected == actual, expected, actual))


def _verify_decision(
    simulator: InternalSimulator,
    receipt: dict[str, Any],
    checks: list[ReplayCheck],
) -> dict[str, Any] | None:
    decision_id = receipt.get("decision_id")
    if not isinstance(decision_id, str):
        checks.append(ReplayCheck("decision_id.present", False, detail="missing decision_id"))
        return None
    checks.append(ReplayCheck("decision_id.present", True))

    row = simulator.decision_row(decision_id)
    if row is None:
        checks.append(ReplayCheck("decision.row_exists", False, expected=decision_id))
        return None
    checks.append(ReplayCheck("decision.row_exists", True))

    decision_hash = _sha256_hex(row["decision_json"])
    checks.append(
        ReplayCheck(
            "decision.hash_matches",
            row["decision_hash"] == decision_hash,
            row["decision_hash"],
            decision_hash,
        )
    )
    checks.append(
        ReplayCheck(
            "decision.id_matches_hash",
            decision_id == f"dec_{decision_hash[:16]}",
            decision_id,
            f"dec_{decision_hash[:16]}",
        )
    )

    kill_switch_hash = _sha256_hex(row["kill_switch_json"])
    checks.append(
        ReplayCheck(
            "kill_switch.hash_matches_db",
            row["kill_switch_hash"] == kill_switch_hash,
            row["kill_switch_hash"],
            kill_switch_hash,
        )
    )
    checks.append(
        ReplayCheck(
            "kill_switch.hash_matches_receipt",
            receipt.get("kill_switch_hash") == row["kill_switch_hash"],
            receipt.get("kill_switch_hash"),
            row["kill_switch_hash"],
        )
    )

    receipt_decision_ts = receipt.get("decision_ts")
    actual_decision_ts = _utc_iso(row["decision_ts"])
    checks.append(
        ReplayCheck(
            "decision_ts.matches_receipt",
            receipt_decision_ts == actual_decision_ts,
            receipt_decision_ts,
            actual_decision_ts,
        )
    )
    return row


def _verify_executions(
    simulator: InternalSimulator,
    receipt: dict[str, Any],
    checks: list[ReplayCheck],
) -> None:
    execution_ids = receipt.get("execution_ids")
    if not isinstance(execution_ids, list) or not execution_ids:
        checks.append(ReplayCheck("execution_ids.present", False))
        return
    checks.append(ReplayCheck("execution_ids.present", True))

    for execution_id in execution_ids:
        row = simulator.execution_row(str(execution_id))
        if row is None:
            checks.append(ReplayCheck(f"execution.{execution_id}.row_exists", False))
            continue
        checks.append(ReplayCheck(f"execution.{execution_id}.row_exists", True))
        expected_hash = execution_hash_for(_ledger_from_row(row))
        checks.append(
            ReplayCheck(
                f"execution.{execution_id}.hash_matches",
                row["execution_hash"] == expected_hash,
                row["execution_hash"],
                expected_hash,
            )
        )
        checks.append(
            ReplayCheck(
                f"execution.{execution_id}.id_matches_hash",
                execution_id == f"exec_{expected_hash[:16]}",
                execution_id,
                f"exec_{expected_hash[:16]}",
            )
        )


def _verify_snapshot_counts(
    simulator: InternalSimulator,
    receipt: dict[str, Any],
    decision_ts: datetime,
    checks: list[ReplayCheck],
) -> None:
    expected = receipt.get("runtime_counts")
    actual = simulator.counts_through(decision_ts)
    checks.append(
        ReplayCheck("runtime_counts.through_snapshot", expected == actual, expected, actual)
    )


def _ledger_from_row(row: dict[str, Any]) -> LedgerRecord:
    return LedgerRecord(
        decision_id=row["decision_id"],
        decision_ts=row["decision_ts"],
        emitted_ts=row["emitted_ts"],
        family=row["family"],
        scenario=CostScenario(row["scenario"]),
        prior_target=row["prior_target"],
        new_target=row["new_target"],
        prior_lots=row["prior_lots"],
        new_lots=row["new_lots"],
        raw_lots=row["raw_lots"],
        effective_b=row["effective_b"],
        price=row["price"],
        market_vol_5d=row["market_vol_5d"],
        fill_cost=row["fill_cost"],
        gross_return=row["gross_return"],
        net_return=row["net_return"],
        degradation_state=row["degradation_state"],
        abstain=row["abstain"],
        abstain_reason=row["abstain_reason"],
    )


def _timestamp_key(ts: datetime) -> str:
    return _utc_iso(ts).replace(":", "")


def _utc_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
