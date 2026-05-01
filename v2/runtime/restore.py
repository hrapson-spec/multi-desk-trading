"""Runtime restore helpers for v2 paper-live state.

B8 restores the B6b/B7 runtime database into a fresh runtime root through
a verified snapshot receipt. It deliberately stops short of broker/PIT
position reconciliation; that remains a later operational slice.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from v2.execution.simulator import InternalSimulator
from v2.runtime.replay import SnapshotVerification, verify_snapshot_receipt


class SnapshotRestoreError(RuntimeError):
    """Raised when a runtime snapshot cannot be restored safely."""


@dataclass(frozen=True)
class SnapshotRestoreReport:
    source_runtime_root: Path
    target_runtime_root: Path
    decision_ts: datetime
    family_decision_rows: int
    execution_rows: int
    snapshot_dirs_copied: int
    source_verification: SnapshotVerification
    restored_verification: SnapshotVerification

    @property
    def ok(self) -> bool:
        return self.source_verification.ok and self.restored_verification.ok


def restore_runtime_snapshot(
    source: InternalSimulator,
    *,
    target_runtime_root: Path,
    decision_ts: datetime | None = None,
    receipt_path: Path | None = None,
    overwrite: bool = False,
) -> SnapshotRestoreReport:
    """Restore runtime DB rows through a verified snapshot into a new root."""
    source_verification = verify_snapshot_receipt(
        source, decision_ts=decision_ts, receipt_path=receipt_path
    )
    if not source_verification.ok:
        failed = ", ".join(check.name for check in source_verification.failures)
        raise SnapshotRestoreError(f"source snapshot verification failed: {failed}")
    if source_verification.receipt is None:
        raise SnapshotRestoreError("source snapshot verification did not load a receipt")

    restore_ts = _parse_utc(source_verification.receipt["decision_ts"])
    target_runtime_root = Path(target_runtime_root)
    if source.runtime_root.resolve() == target_runtime_root.resolve():
        raise SnapshotRestoreError("target_runtime_root must differ from source runtime root")
    _prepare_target(target_runtime_root, overwrite=overwrite)

    target = InternalSimulator.open(target_runtime_root)
    try:
        family_rows = _copy_family_decisions(source, target, restore_ts)
        execution_rows = _copy_execution_ledger(source, target, restore_ts)
        snapshot_dirs = _copy_snapshot_dirs(source.runtime_root, target_runtime_root, restore_ts)
        _write_restore_report(
            target_runtime_root,
            source_root=source.runtime_root,
            decision_ts=restore_ts,
            family_rows=family_rows,
            execution_rows=execution_rows,
            snapshot_dirs=snapshot_dirs,
        )
        restored_verification = verify_snapshot_receipt(target, decision_ts=restore_ts)
    finally:
        target.close()

    if not restored_verification.ok:
        failed = ", ".join(check.name for check in restored_verification.failures)
        raise SnapshotRestoreError(f"restored snapshot verification failed: {failed}")

    return SnapshotRestoreReport(
        source_runtime_root=source.runtime_root,
        target_runtime_root=target_runtime_root,
        decision_ts=restore_ts,
        family_decision_rows=family_rows,
        execution_rows=execution_rows,
        snapshot_dirs_copied=snapshot_dirs,
        source_verification=source_verification,
        restored_verification=restored_verification,
    )


def _prepare_target(target_runtime_root: Path, *, overwrite: bool) -> None:
    if target_runtime_root.exists() and any(target_runtime_root.iterdir()):
        if not overwrite:
            raise SnapshotRestoreError(
                f"target runtime root is not empty: {target_runtime_root}"
            )
        shutil.rmtree(target_runtime_root)
    target_runtime_root.mkdir(parents=True, exist_ok=True)


def _copy_family_decisions(
    source: InternalSimulator, target: InternalSimulator, decision_ts: datetime
) -> int:
    columns = (
        "decision_id, family, decision_ts, emitted_ts, decision_json, decision_hash, "
        "family_forecast_hash, forecast_ids_json, kill_switch_json, kill_switch_hash, created_at"
    )
    rows = source.conn.execute(
        f"""
        SELECT {columns}
        FROM family_decisions
        WHERE decision_ts <= ?
        ORDER BY decision_ts ASC
        """,
        [_naive_utc(decision_ts)],
    ).fetchall()
    for row in rows:
        target.conn.execute(
            f"INSERT INTO family_decisions ({columns}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            list(row),
        )
    return len(rows)


def _copy_execution_ledger(
    source: InternalSimulator, target: InternalSimulator, decision_ts: datetime
) -> int:
    columns = (
        "execution_id, execution_hash, decision_id, family, decision_ts, emitted_ts, scenario, "
        "prior_target, new_target, prior_lots, new_lots, raw_lots, effective_b, price, "
        "market_vol_5d, fill_cost, gross_return, net_return, degradation_state, abstain, "
        "abstain_reason, created_at"
    )
    rows = source.conn.execute(
        f"""
        SELECT {columns}
        FROM execution_ledger
        WHERE decision_ts <= ?
        ORDER BY decision_ts ASC, scenario ASC
        """,
        [_naive_utc(decision_ts)],
    ).fetchall()
    for row in rows:
        target.conn.execute(
            f"""
            INSERT INTO execution_ledger ({columns})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            list(row),
        )
    return len(rows)


def _copy_snapshot_dirs(
    source_runtime_root: Path, target_runtime_root: Path, decision_ts: datetime
) -> int:
    source_snapshots = source_runtime_root / "snapshots"
    if not source_snapshots.exists():
        return 0
    target_snapshots = target_runtime_root / "snapshots"
    target_snapshots.mkdir(parents=True, exist_ok=True)

    copied = 0
    for snapshot_dir in sorted(path for path in source_snapshots.iterdir() if path.is_dir()):
        receipt_path = snapshot_dir / "receipt.json"
        if not receipt_path.exists():
            continue
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt_ts = _parse_utc(receipt["decision_ts"])
        if receipt_ts <= decision_ts:
            shutil.copytree(snapshot_dir, target_snapshots / snapshot_dir.name)
            copied += 1
    return copied


def _write_restore_report(
    target_runtime_root: Path,
    *,
    source_root: Path,
    decision_ts: datetime,
    family_rows: int,
    execution_rows: int,
    snapshot_dirs: int,
) -> None:
    payload: dict[str, Any] = {
        "source_runtime_root": str(source_root),
        "target_runtime_root": str(target_runtime_root),
        "decision_ts": _utc_iso(decision_ts),
        "family_decision_rows": family_rows,
        "execution_rows": execution_rows,
        "snapshot_dirs_copied": snapshot_dirs,
    }
    (target_runtime_root / "restore_report.json").write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _parse_utc(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _naive_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(UTC).replace(tzinfo=None)


def _utc_iso(ts: datetime) -> str:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")
