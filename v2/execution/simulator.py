"""Internal simulator runtime store for B6b paper-live.

The simulator persists runtime decisions separately from the PIT store:

    runtime_root/paper_live.duckdb

Each tick writes one family-level `DecisionV2` row and one execution row
per cost scenario. Runtime IDs are content-addressed and deterministic;
`created_at` timestamps are operational metadata and are excluded from
all hashes and IDs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import duckdb
from pydantic import BaseModel

from v2.contracts.decision_v2 import DecisionV2
from v2.eval.cost_model import CostScenario

_RUNTIME_DDL = """
CREATE TABLE IF NOT EXISTS family_decisions (
    decision_id          TEXT PRIMARY KEY,
    family               TEXT NOT NULL,
    decision_ts          TIMESTAMP NOT NULL,
    emitted_ts           TIMESTAMP NOT NULL,
    decision_json        TEXT NOT NULL,
    decision_hash        TEXT NOT NULL,
    family_forecast_hash TEXT,
    forecast_ids_json    TEXT NOT NULL,
    kill_switch_json     TEXT NOT NULL,
    kill_switch_hash     TEXT NOT NULL,
    created_at           TIMESTAMP NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS family_decisions_family_ts
    ON family_decisions (family, decision_ts);

CREATE TABLE IF NOT EXISTS execution_ledger (
    execution_id         TEXT PRIMARY KEY,
    execution_hash       TEXT NOT NULL,
    decision_id          TEXT NOT NULL,
    family               TEXT NOT NULL,
    decision_ts          TIMESTAMP NOT NULL,
    emitted_ts           TIMESTAMP NOT NULL,
    scenario             TEXT NOT NULL,
    prior_target         DOUBLE NOT NULL,
    new_target           DOUBLE NOT NULL,
    prior_lots           INTEGER NOT NULL,
    new_lots             INTEGER NOT NULL,
    raw_lots             DOUBLE NOT NULL,
    effective_b          DOUBLE NOT NULL,
    price                DOUBLE NOT NULL,
    market_vol_5d        DOUBLE NOT NULL,
    fill_cost            DOUBLE NOT NULL,
    gross_return         DOUBLE NOT NULL,
    net_return           DOUBLE NOT NULL,
    degradation_state    TEXT NOT NULL,
    abstain              BOOLEAN NOT NULL,
    abstain_reason       TEXT,
    created_at           TIMESTAMP NOT NULL,
    FOREIGN KEY(decision_id) REFERENCES family_decisions(decision_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS execution_ledger_family_ts_scenario
    ON execution_ledger (family, decision_ts, scenario);
"""


class RuntimeLedgerConflictError(RuntimeError):
    """Raised when a duplicate runtime row has different content."""


RuntimeLedgerConflict = RuntimeLedgerConflictError


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    decision_hash: str
    family_forecast_hash: str | None
    forecast_ids: tuple[str, ...]
    kill_switch_hash: str


@dataclass(frozen=True)
class LedgerRecord:
    decision_ts: datetime
    emitted_ts: datetime
    family: str
    scenario: CostScenario
    prior_target: float
    new_target: float
    prior_lots: int
    new_lots: int
    raw_lots: float
    effective_b: float
    price: float
    market_vol_5d: float
    fill_cost: float
    gross_return: float
    net_return: float
    degradation_state: str
    decision_id: str | None = None
    forecast_ids: tuple[str, ...] = field(default_factory=tuple)
    abstain: bool = False
    abstain_reason: str | None = None


class InternalSimulator:
    """DuckDB-backed paper-live decision and execution ledger."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, runtime_root: Path):
        self.conn = conn
        self.runtime_root = Path(runtime_root)
        self.conn.execute(_RUNTIME_DDL)

    @classmethod
    def open(cls, runtime_root: Path) -> InternalSimulator:
        runtime_root = Path(runtime_root)
        runtime_root.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(runtime_root / "paper_live.duckdb"))
        return cls(conn, runtime_root)

    def __enter__(self) -> InternalSimulator:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def record_decision(
        self,
        *,
        decision: DecisionV2,
        family_forecast_hash: str | None,
        forecast_ids: tuple[str, ...],
        kill_switch_state: Any,
        emitted_ts: datetime,
    ) -> DecisionRecord:
        decision_json = _canonical_json(decision)
        decision_hash = _sha256_hex(decision_json)
        decision_id = f"dec_{decision_hash[:16]}"
        forecast_ids = tuple(forecast_ids)
        forecast_ids_json = _canonical_json(list(forecast_ids))
        kill_switch_json = _canonical_json(kill_switch_state)
        kill_switch_hash = _sha256_hex(kill_switch_json)

        row = self.conn.execute(
            """
            SELECT decision_id, decision_hash, family_forecast_hash,
                   forecast_ids_json, kill_switch_hash
            FROM family_decisions
            WHERE family = ? AND decision_ts = ?
            """,
            [decision.family, _naive_utc(decision.decision_ts)],
        ).fetchone()
        if row is not None:
            if (
                row[0] == decision_id
                and row[1] == decision_hash
                and row[2] == family_forecast_hash
                and row[3] == forecast_ids_json
                and row[4] == kill_switch_hash
            ):
                return DecisionRecord(
                    decision_id=row[0],
                    decision_hash=row[1],
                    family_forecast_hash=row[2],
                    forecast_ids=tuple(json.loads(row[3])),
                    kill_switch_hash=row[4],
                )
            raise RuntimeLedgerConflictError(
                "decision already exists for "
                f"{decision.family} at {decision.decision_ts.isoformat()}"
            )

        self.conn.execute(
            """
            INSERT INTO family_decisions (
                decision_id, family, decision_ts, emitted_ts, decision_json,
                decision_hash, family_forecast_hash, forecast_ids_json,
                kill_switch_json, kill_switch_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                decision_id,
                decision.family,
                _naive_utc(decision.decision_ts),
                _naive_utc(emitted_ts),
                decision_json,
                decision_hash,
                family_forecast_hash,
                forecast_ids_json,
                kill_switch_json,
                kill_switch_hash,
                _utcnow_naive(),
            ],
        )
        return DecisionRecord(
            decision_id=decision_id,
            decision_hash=decision_hash,
            family_forecast_hash=family_forecast_hash,
            forecast_ids=forecast_ids,
            kill_switch_hash=kill_switch_hash,
        )

    def record_tick(self, record: LedgerRecord) -> str:
        if not record.decision_id:
            raise ValueError("LedgerRecord.decision_id is required before persistence")
        execution_hash = execution_hash_for(record)
        execution_id = f"exec_{execution_hash[:16]}"

        row = self.conn.execute(
            """
            SELECT execution_id, execution_hash
            FROM execution_ledger
            WHERE family = ? AND decision_ts = ? AND scenario = ?
            """,
            [record.family, _naive_utc(record.decision_ts), record.scenario.value],
        ).fetchone()
        if row is not None:
            if row[0] == execution_id and row[1] == execution_hash:
                return row[0]
            raise RuntimeLedgerConflictError(
                "execution row already exists for "
                f"{record.family} at {record.decision_ts.isoformat()} / {record.scenario.value}"
            )

        self.conn.execute(
            """
            INSERT INTO execution_ledger (
                execution_id, execution_hash, decision_id, family, decision_ts, emitted_ts,
                scenario, prior_target, new_target, prior_lots, new_lots, raw_lots,
                effective_b, price, market_vol_5d, fill_cost, gross_return, net_return,
                degradation_state, abstain, abstain_reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                execution_id,
                execution_hash,
                record.decision_id,
                record.family,
                _naive_utc(record.decision_ts),
                _naive_utc(record.emitted_ts),
                record.scenario.value,
                record.prior_target,
                record.new_target,
                record.prior_lots,
                record.new_lots,
                record.raw_lots,
                record.effective_b,
                record.price,
                record.market_vol_5d,
                record.fill_cost,
                record.gross_return,
                record.net_return,
                record.degradation_state,
                record.abstain,
                record.abstain_reason,
                _utcnow_naive(),
            ],
        )
        return execution_id

    def latest_decision(self, family: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT decision_id, decision_json, decision_hash, family_forecast_hash,
                   forecast_ids_json, kill_switch_hash
            FROM family_decisions
            WHERE family = ?
            ORDER BY decision_ts DESC
            LIMIT 1
            """,
            [family],
        ).fetchone()
        if row is None:
            return None
        return {
            "decision_id": row[0],
            "decision": DecisionV2.model_validate_json(row[1]),
            "decision_hash": row[2],
            "family_forecast_hash": row[3],
            "forecast_ids": tuple(json.loads(row[4])),
            "kill_switch_hash": row[5],
        }

    def latest(self, family: str, scenario: CostScenario) -> LedgerRecord | None:
        row = self.conn.execute(
            """
            SELECT decision_id, decision_ts, emitted_ts, family, scenario,
                   prior_target, new_target, prior_lots, new_lots, raw_lots, effective_b,
                   price, market_vol_5d, fill_cost, gross_return, net_return,
                   degradation_state, abstain, abstain_reason
            FROM execution_ledger
            WHERE family = ? AND scenario = ?
            ORDER BY decision_ts DESC
            LIMIT 1
            """,
            [family, scenario.value],
        ).fetchone()
        return _record_from_row(row) if row is not None else None

    def all_ticks(self, family: str, scenario: CostScenario) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT decision_id, decision_ts, emitted_ts, new_target, new_lots,
                   raw_lots, effective_b, net_return, abstain, abstain_reason,
                   degradation_state
            FROM execution_ledger
            WHERE family = ? AND scenario = ?
            ORDER BY decision_ts ASC
            """,
            [family, scenario.value],
        ).fetchall()
        return [
            {
                "decision_id": r[0],
                "decision_ts": _as_utc(r[1]),
                "emitted_ts": _as_utc(r[2]),
                "new_target": r[3],
                "new_lots": r[4],
                "raw_lots": r[5],
                "effective_b": r[6],
                "net_return": r[7],
                "abstain": r[8],
                "abstain_reason": r[9],
                "degradation_state": r[10],
            }
            for r in rows
        ]

    def counts(self) -> dict[str, int]:
        decision_count = self.conn.execute("SELECT count(*) FROM family_decisions").fetchone()[0]
        execution_count = self.conn.execute("SELECT count(*) FROM execution_ledger").fetchone()[0]
        return {"family_decisions": decision_count, "execution_ledger": execution_count}

    def counts_through(self, decision_ts: datetime) -> dict[str, int]:
        decision_count = self.conn.execute(
            "SELECT count(*) FROM family_decisions WHERE decision_ts <= ?",
            [_naive_utc(decision_ts)],
        ).fetchone()[0]
        execution_count = self.conn.execute(
            "SELECT count(*) FROM execution_ledger WHERE decision_ts <= ?",
            [_naive_utc(decision_ts)],
        ).fetchone()[0]
        return {"family_decisions": decision_count, "execution_ledger": execution_count}

    def decision_row(self, decision_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT decision_id, family, decision_ts, emitted_ts, decision_json,
                   decision_hash, family_forecast_hash, forecast_ids_json,
                   kill_switch_json, kill_switch_hash
            FROM family_decisions
            WHERE decision_id = ?
            """,
            [decision_id],
        ).fetchone()
        if row is None:
            return None
        return {
            "decision_id": row[0],
            "family": row[1],
            "decision_ts": _as_utc(row[2]),
            "emitted_ts": _as_utc(row[3]),
            "decision_json": row[4],
            "decision_hash": row[5],
            "family_forecast_hash": row[6],
            "forecast_ids_json": row[7],
            "kill_switch_json": row[8],
            "kill_switch_hash": row[9],
        }

    def execution_row(self, execution_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT execution_id, execution_hash, decision_id, family, decision_ts,
                   emitted_ts, scenario, prior_target, new_target, prior_lots,
                   new_lots, raw_lots, effective_b, price, market_vol_5d,
                   fill_cost, gross_return, net_return, degradation_state,
                   abstain, abstain_reason
            FROM execution_ledger
            WHERE execution_id = ?
            """,
            [execution_id],
        ).fetchone()
        if row is None:
            return None
        return {
            "execution_id": row[0],
            "execution_hash": row[1],
            "decision_id": row[2],
            "family": row[3],
            "decision_ts": _as_utc(row[4]),
            "emitted_ts": _as_utc(row[5]),
            "scenario": row[6],
            "prior_target": row[7],
            "new_target": row[8],
            "prior_lots": row[9],
            "new_lots": row[10],
            "raw_lots": row[11],
            "effective_b": row[12],
            "price": row[13],
            "market_vol_5d": row[14],
            "fill_cost": row[15],
            "gross_return": row[16],
            "net_return": row[17],
            "degradation_state": row[18],
            "abstain": row[19],
            "abstain_reason": row[20],
        }

    def write_snapshot_receipt(
        self,
        *,
        decision_ts: datetime,
        decision_id: str,
        execution_ids: tuple[str, ...],
        kill_switch_hash: str,
        code_commit: str,
        contract_hash: str,
        pit_manifest_hash: str | None = None,
    ) -> Path:
        receipt_dir = self.runtime_root / "snapshots" / _timestamp_key(decision_ts)
        receipt_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "decision_ts": _utc_iso(decision_ts),
            "decision_id": decision_id,
            "execution_ids": list(execution_ids),
            "kill_switch_hash": kill_switch_hash,
            "code_commit": code_commit,
            "contract_hash": contract_hash,
            "pit_manifest_hash": pit_manifest_hash,
            "runtime_counts": self.counts(),
        }
        receipt_json = _canonical_json(payload)
        digest = _sha256_hex(receipt_json)
        receipt_path = receipt_dir / "receipt.json"
        hash_path = receipt_dir / "receipt.sha256"
        receipt_path.write_text(receipt_json + "\n", encoding="utf-8")
        hash_path.write_text(digest + "\n", encoding="utf-8")
        return receipt_path


def decision_hash_for(decision: DecisionV2) -> str:
    return _sha256_hex(_canonical_json(decision))


def content_hash(value: Any) -> str:
    return _sha256_hex(_canonical_json(value))


def execution_hash_for(record: LedgerRecord) -> str:
    payload = {
        "decision_id": record.decision_id,
        "decision_ts": _utc_iso(record.decision_ts),
        "emitted_ts": _utc_iso(record.emitted_ts),
        "family": record.family,
        "scenario": record.scenario.value,
        "prior_target": record.prior_target,
        "new_target": record.new_target,
        "prior_lots": record.prior_lots,
        "new_lots": record.new_lots,
        "raw_lots": record.raw_lots,
        "effective_b": record.effective_b,
        "price": record.price,
        "market_vol_5d": record.market_vol_5d,
        "fill_cost": record.fill_cost,
        "gross_return": record.gross_return,
        "net_return": record.net_return,
        "degradation_state": record.degradation_state,
        "abstain": record.abstain,
        "abstain_reason": record.abstain_reason,
    }
    return _sha256_hex(_canonical_json(payload))


# -- helpers -----------------------------------------------------------------


def _record_from_row(row: tuple[Any, ...]) -> LedgerRecord:
    return LedgerRecord(
        decision_id=row[0],
        decision_ts=_as_utc(row[1]),
        emitted_ts=_as_utc(row[2]),
        family=row[3],
        scenario=CostScenario(row[4]),
        prior_target=row[5],
        new_target=row[6],
        prior_lots=row[7],
        new_lots=row[8],
        raw_lots=row[9],
        effective_b=row[10],
        price=row[11],
        market_vol_5d=row[12],
        fill_cost=row[13],
        gross_return=row[14],
        net_return=row[15],
        degradation_state=row[16],
        abstain=row[17],
        abstain_reason=row[18],
    )


def _canonical_json(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, datetime):
        return _utc_iso(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(k): _jsonable(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _naive_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts
    return ts.astimezone(UTC).replace(tzinfo=None)


def _as_utc(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _utc_iso(ts: datetime) -> str:
    return _as_utc(ts).isoformat().replace("+00:00", "Z")


def _timestamp_key(ts: datetime) -> str:
    return _utc_iso(ts).replace(":", "")


def _utcnow_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
