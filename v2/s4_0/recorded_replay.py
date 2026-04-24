"""S4-0 recorded replay runner.

This module executes the first no-money S4 rehearsal against a local
recorded-replay CSV export. It deliberately does not download vendor data,
store credentials, or require licensed market data. The caller must provide a
local replay file plus no-money run-control artefacts before the run can start.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from v2.contracts.decision_unit import DecisionUnit
from v2.contracts.decision_v2 import DegradationState
from v2.contracts.forecast_v2 import CalibrationMetadata, ForecastV2
from v2.execution.adapter import AdapterParams
from v2.execution.control_law import ControlLawParams
from v2.execution.degradation import ExposureState
from v2.execution.simulator import InternalSimulator, content_hash
from v2.feature_view.view import FeatureView
from v2.paper_live.loop import MarketTickContext, run_decision_tick
from v2.runtime.kill_switch import load_kill_switch
from v2.runtime.replay import SnapshotVerification, verify_snapshot_receipt
from v2.runtime.restore import restore_runtime_snapshot
from v2.s4_0.replay_quality import ReplayTick, analyze_tick_quality

_FAMILY = "oil_wti_5d"
_DESK = "s4_0_recorded_replay_desk"
_STAGE = "S4-0 recorded replay"
_TARGET_VARIABLE = "WTI_FRONT_1W_LOG_RETURN"
_TARGET_HORIZON = "5d"
_REQUIRED_RUN_CONTROL_FILES = (
    "owner_clearance_decision.md",
    "no_money_attestation.md",
)
_OPTIONAL_DATA_SOURCE_FILES = (
    "data_source_summary.md",
    "source_rights_note.md",
    "licence_boundary_table.md",
    "vendor_terms_summary.md",
    "exchange_route_summary.md",
    "reviewer_access_model.md",
    "unresolved_licence_questions.md",
)
_OWNER_APPROVAL_LINE = "- [x] Approved for S4-0 no-money recorded replay execution."
_OWNER_APPROVAL_LINE_FREE = (
    "- [x] Approved for S4-0 local/free recorded replay execution."
)
_OWNER_APPROVAL_LINE_S4_0F = (
    "- [x] Approved for S4-0F no-money free-data rehearsal execution."
)
_OWNER_APPROVAL_LINES = (
    _OWNER_APPROVAL_LINE,
    _OWNER_APPROVAL_LINE_FREE,
    _OWNER_APPROVAL_LINE_S4_0F,
)
_OWNER_REJECTION_LINE = "- [x] Not approved; blocker remains."
_NO_MONEY_LINES = (
    "- [x] No live broker route is configured.",
    "- [x] No funded account is connected.",
    "- [x] No live order API key is present in the run environment.",
    "- [x] Execution is internal simulation only.",
    "- [x] Any paper/live brokerage integration is out of scope for this run.",
)


class S40PreflightError(RuntimeError):
    """Raised when S4-0 execution gates are not satisfied."""


@dataclass(frozen=True)
class S40ReplayConfig:
    run_id: str
    evidence_root: Path
    raw_feed_csv: Path
    run_control_dir: Path
    front_symbol: str
    next_symbol: str
    session_start: datetime
    session_end: datetime
    vendor: str = "local"
    dataset: str = "local/free/synthetic recorded replay"
    market_depth: str = "unknown"
    decision_interval_minutes: int = 60
    market_vol_5d: float = 0.04
    reference_risk_5d_usd: float = 100_000.0
    contract_multiplier_bbl: float = 1_000.0
    max_abs_lots: int = 10
    control_gain: float = 0.25
    copy_raw: bool = False
    restore_last_snapshot: bool = True
    prereg_hash: str = "sha256:s4-0-prereg"
    code_commit: str = "s4-0-local"
    contract_hash: str = "sha256:s4-0-contract"
    release_calendar_version: str = "cme-cl-calendar:s4-0"
    stage: str = _STAGE

    @property
    def run_root(self) -> Path:
        return self.evidence_root / self.run_id

    @property
    def licence_clearance_dir(self) -> Path:
        """Backward-compatible alias for older local configs."""
        return self.run_control_dir

    @classmethod
    def from_yaml(cls, path: Path) -> S40ReplayConfig:
        path = Path(path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        base = path.parent

        def _path(name: str) -> Path:
            value = Path(str(data[name]))
            return value if value.is_absolute() else base / value

        payload = {
            **data,
            "evidence_root": _path("evidence_root"),
            "raw_feed_csv": _path("raw_feed_csv"),
            "run_control_dir": _path(
                "run_control_dir"
                if "run_control_dir" in data
                else "licence_clearance_dir"
            ),
            "session_start": _parse_utc(str(data["session_start"])),
            "session_end": _parse_utc(str(data["session_end"])),
        }
        payload.pop("licence_clearance_dir", None)
        return cls(**payload)


@dataclass(frozen=True)
class MarketEvent:
    ts_event: datetime
    ts_recv: datetime | None
    symbol: str
    price: float
    size: float | None
    sequence: str | None
    source_row: dict[str, str]
    source_row_index: int
    source_row_hash: str


@dataclass(frozen=True)
class DecisionSample:
    event: MarketEvent
    realised_return_since_last_tick: float


@dataclass(frozen=True)
class DataQualityReport:
    input_rows: int
    accepted_rows: int
    session_rows: int
    rejected_rows: int
    duplicate_rows: int
    out_of_order_rows: int
    front_rows: int
    next_rows: int
    max_front_gap_seconds: float | None
    decision_samples: int
    symbol_counts: dict[str, int] = field(default_factory=dict)

    @property
    def hard_failures(self) -> tuple[str, ...]:
        failures: list[str] = []
        if self.accepted_rows == 0:
            failures.append("no accepted replay rows")
        if self.front_rows == 0:
            failures.append("front contract has no rows")
        if self.next_rows == 0:
            failures.append("next contract has no rows")
        if self.decision_samples == 0:
            failures.append("no decision samples generated")
        return tuple(failures)


@dataclass(frozen=True)
class S40RecordedReplayReport:
    run_id: str
    run_root: Path
    runtime_root: Path
    restore_root: Path | None
    manifest_path: Path
    data_quality: DataQualityReport
    runtime_counts: dict[str, int]
    replay_verifications: tuple[SnapshotVerification, ...]
    restored_counts: dict[str, int] | None
    stop_go: str
    exceptions: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.stop_go == "green"


def run_s4_0_recorded_replay(
    config: S40ReplayConfig, *, overwrite: bool = False
) -> S40RecordedReplayReport:
    """Execute an S4-0 recorded replay run from local replay data."""
    _preflight(config)
    run_root = _prepare_run_root(config.run_root, overwrite=overwrite)
    dirs = _prepare_evidence_dirs(run_root)

    raw_events = _load_market_events(config)
    accepted, quality = _normalise_events(config, raw_events)
    if quality.hard_failures:
        raise S40PreflightError("; ".join(quality.hard_failures))

    _write_run_control(config, dirs["00_run_control"])
    _write_data_source(config, dirs["01_data_source"])
    _write_reference_data(config, dirs["02_reference_data"])
    _write_raw_evidence(config, raw_events, dirs["03_raw_feed"])
    _write_normalized_events(accepted, dirs["04_normalized_feed"])
    _write_data_quality(quality, accepted, dirs["05_data_quality"])

    runtime_root = run_root / "runtime"
    restore_root = run_root / "15_restore" / "runtime_restored"
    samples = _decision_samples(config, accepted)
    replay_verifications: list[SnapshotVerification] = []
    exceptions: list[str] = []

    simulator = InternalSimulator.open(runtime_root)
    try:
        runtime_counts = _run_decision_samples(
            config,
            samples,
            simulator=simulator,
            feature_dir=dirs["06_features"],
            forecast_dir=dirs["07_forecasts"],
            decision_dir=dirs["08_decisions"],
        )
        _write_simulation_ledger(simulator, dirs["09_simulation"])
        _write_runtime_controls(simulator.runtime_root, dirs["10_runtime_controls"])
        _write_incidents(simulator.runtime_root, dirs["11_incidents"])
        _write_monitoring(config, quality, runtime_counts, dirs["12_monitoring"])

        for sample in samples:
            verification = verify_snapshot_receipt(simulator, decision_ts=sample.event.ts_event)
            replay_verifications.append(verification)
            if not verification.ok:
                failed = ", ".join(check.name for check in verification.failures)
                exceptions.append(
                    f"replay verification failed at {sample.event.ts_event}: {failed}"
                )
        _write_replay_report(replay_verifications, dirs["14_replay"])

        restored_counts: dict[str, int] | None = None
        if config.restore_last_snapshot:
            restore_report = restore_runtime_snapshot(
                simulator,
                target_runtime_root=restore_root,
                decision_ts=samples[-1].event.ts_event,
                overwrite=True,
            )
            restored = InternalSimulator.open(restore_root)
            try:
                restored_counts = restored.counts()
            finally:
                restored.close()
            _write_restore_summary(restore_report.ok, restored_counts, dirs["15_restore"])
            if not restore_report.ok:
                exceptions.append("restore verification failed")
        else:
            _write_restore_summary(None, None, dirs["15_restore"])
    finally:
        simulator.close()

    _write_reconciliation(quality, runtime_counts, dirs["13_reconciliation"])
    stop_go = _stop_go(quality, replay_verifications, restored_counts, exceptions)
    _write_final_report(config, quality, runtime_counts, stop_go, exceptions, dirs["16_report"])
    manifest_path = _write_manifest(config, run_root, quality, runtime_counts, exceptions, stop_go)

    return S40RecordedReplayReport(
        run_id=config.run_id,
        run_root=run_root,
        runtime_root=runtime_root,
        restore_root=restore_root if config.restore_last_snapshot else None,
        manifest_path=manifest_path,
        data_quality=quality,
        runtime_counts=runtime_counts,
        replay_verifications=tuple(replay_verifications),
        restored_counts=restored_counts,
        stop_go=stop_go,
        exceptions=tuple(exceptions),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run S4-0 recorded replay")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    report = run_s4_0_recorded_replay(
        S40ReplayConfig.from_yaml(args.config),
        overwrite=args.overwrite,
    )
    payload = {
        "run_id": report.run_id,
        "run_root": str(report.run_root),
        "stop_go": report.stop_go,
        "runtime_counts": report.runtime_counts,
        "manifest_path": str(report.manifest_path),
        "exceptions": list(report.exceptions),
    }
    print(json.dumps(payload, sort_keys=True))
    return 0 if report.ok else 2


def _preflight(config: S40ReplayConfig) -> None:
    if config.session_end <= config.session_start:
        raise S40PreflightError("session_end must be after session_start")
    if config.decision_interval_minutes <= 0:
        raise S40PreflightError("decision_interval_minutes must be > 0")
    if config.market_vol_5d <= 0:
        raise S40PreflightError("market_vol_5d must be > 0")
    if not config.raw_feed_csv.exists():
        raise S40PreflightError(f"raw_feed_csv is missing: {config.raw_feed_csv}")
    if not config.run_control_dir.exists():
        raise S40PreflightError(f"run_control_dir is missing: {config.run_control_dir}")
    missing = [
        name
        for name in _REQUIRED_RUN_CONTROL_FILES
        if not (config.run_control_dir / name).exists()
    ]
    if missing:
        raise S40PreflightError("run-control files missing: " + ", ".join(missing))
    owner_clearance = (config.run_control_dir / "owner_clearance_decision.md").read_text(
        encoding="utf-8"
    )
    if _OWNER_REJECTION_LINE in owner_clearance or not any(
        line in owner_clearance for line in _OWNER_APPROVAL_LINES
    ):
        raise S40PreflightError(
            "owner_clearance_decision.md must explicitly approve S4-0 execution"
        )
    no_money = (config.run_control_dir / "no_money_attestation.md").read_text(
        encoding="utf-8"
    )
    missing_attestations = [line for line in _NO_MONEY_LINES if line not in no_money]
    if missing_attestations:
        raise S40PreflightError(
            "no_money_attestation.md missing checked attestations: "
            + ", ".join(missing_attestations)
        )


def _prepare_run_root(run_root: Path, *, overwrite: bool) -> Path:
    if run_root.exists() and any(run_root.iterdir()):
        if not overwrite:
            raise S40PreflightError(f"run root is not empty: {run_root}")
        shutil.rmtree(run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    return run_root


def _prepare_evidence_dirs(run_root: Path) -> dict[str, Path]:
    names = (
        "00_run_control",
        "01_data_source",
        "02_reference_data",
        "03_raw_feed",
        "04_normalized_feed",
        "05_data_quality",
        "06_features",
        "07_forecasts",
        "08_decisions",
        "09_simulation",
        "10_runtime_controls",
        "11_incidents",
        "12_monitoring",
        "13_reconciliation",
        "14_replay",
        "15_restore",
        "16_report",
    )
    dirs = {}
    for name in names:
        path = run_root / name
        path.mkdir(parents=True, exist_ok=True)
        dirs[name] = path
    return dirs


def _load_market_events(config: S40ReplayConfig) -> list[MarketEvent]:
    events: list[MarketEvent] = []
    seen_columns: set[str] | None = None
    with config.raw_feed_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise S40PreflightError("raw replay CSV has no header")
        seen_columns = set(reader.fieldnames)
        required = {"ts_event", "symbol", "price"}
        missing = required - seen_columns
        if missing:
            raise S40PreflightError("raw replay CSV missing columns: " + ", ".join(sorted(missing)))
        for index, row in enumerate(reader, start=2):
            try:
                ts_event = _parse_utc(row["ts_event"])
                ts_recv = _parse_utc(row["ts_recv"]) if row.get("ts_recv") else None
                price = float(row["price"])
            except (KeyError, TypeError, ValueError) as exc:
                raise S40PreflightError(f"invalid raw replay row {index}: {exc}") from exc
            if price <= 0:
                raise S40PreflightError(f"invalid non-positive price at row {index}: {price}")
            events.append(
                MarketEvent(
                    ts_event=ts_event,
                    ts_recv=ts_recv,
                    symbol=str(row["symbol"]),
                    price=price,
                    size=float(row["size"]) if row.get("size") else None,
                    sequence=row.get("sequence") or row.get("seq"),
                    source_row=dict(row),
                    source_row_index=index,
                    source_row_hash=_hash_dict(row),
                )
            )
    if seen_columns is None:
        raise S40PreflightError("raw replay CSV has no columns")
    return events


def _normalise_events(
    config: S40ReplayConfig, events: list[MarketEvent]
) -> tuple[list[MarketEvent], DataQualityReport]:
    allowed = {config.front_symbol, config.next_symbol}
    session_rows = [
        event
        for event in events
        if config.session_start <= event.ts_event <= config.session_end
        and event.symbol in allowed
    ]
    accepted = sorted(
        session_rows,
        key=lambda event: (event.ts_event, event.sequence or "", event.source_row_index),
    )
    hashes = [event.source_row_hash for event in accepted]
    duplicate_rows = len(hashes) - len(set(hashes))

    out_of_order = 0
    prior: datetime | None = None
    for event in session_rows:
        if prior is not None and event.ts_event < prior:
            out_of_order += 1
        prior = event.ts_event

    symbol_counts: dict[str, int] = {}
    for event in accepted:
        symbol_counts[event.symbol] = symbol_counts.get(event.symbol, 0) + 1
    front = [event for event in accepted if event.symbol == config.front_symbol]
    gaps = [
        (b.ts_event - a.ts_event).total_seconds()
        for a, b in zip(front, front[1:], strict=False)
    ]
    quality = DataQualityReport(
        input_rows=len(events),
        accepted_rows=len(accepted),
        session_rows=len(session_rows),
        rejected_rows=len(events) - len(session_rows),
        duplicate_rows=duplicate_rows,
        out_of_order_rows=out_of_order,
        front_rows=len(front),
        next_rows=symbol_counts.get(config.next_symbol, 0),
        max_front_gap_seconds=max(gaps) if gaps else None,
        decision_samples=len(_decision_samples(config, accepted)) if accepted else 0,
        symbol_counts=symbol_counts,
    )
    return accepted, quality


def _decision_samples(config: S40ReplayConfig, events: list[MarketEvent]) -> list[DecisionSample]:
    interval = timedelta(minutes=config.decision_interval_minutes)
    front = [event for event in events if event.symbol == config.front_symbol]
    buckets: dict[int, MarketEvent] = {}
    for event in front:
        bucket = int(
            (event.ts_event - config.session_start).total_seconds()
            // interval.total_seconds()
        )
        buckets[bucket] = event

    samples: list[DecisionSample] = []
    previous_price: float | None = None
    for bucket in sorted(buckets):
        event = buckets[bucket]
        realised = 0.0
        if previous_price is not None:
            realised = math.log(event.price / previous_price)
        previous_price = event.price
        samples.append(DecisionSample(event=event, realised_return_since_last_tick=realised))
    return samples


def _run_decision_samples(
    config: S40ReplayConfig,
    samples: list[DecisionSample],
    *,
    simulator: InternalSimulator,
    feature_dir: Path,
    forecast_dir: Path,
    decision_dir: Path,
) -> dict[str, int]:
    exposure = ExposureState(
        state=DegradationState.HEALTHY,
        current_target=0.0,
        last_valid_target=0.0,
        ticks_since_valid=0,
    )
    prior_lots = 0
    lineage: list[dict[str, Any]] = []
    for sample in samples:
        kill_switch = load_kill_switch(simulator.runtime_root, family=_FAMILY)
        forecast = _forecast_for_sample(config, sample)
        context = MarketTickContext(
            decision_ts=sample.event.ts_event,
            emitted_ts=sample.event.ts_event,
            family=_FAMILY,
            forecasts=[forecast],
            price=sample.event.price,
            realised_return_since_last_tick=sample.realised_return_since_last_tick,
            market_vol_5d=config.market_vol_5d,
            prior_exposure=exposure,
            prior_lots=prior_lots,
            kill_switch_state=kill_switch.effective_state(_FAMILY),
            kill_switch_halting=kill_switch.is_halting(_FAMILY),
            override_abstain_reason=(
                f"kill_switch:{kill_switch.reason(_FAMILY)}"
                if kill_switch.is_halting(_FAMILY)
                else None
            ),
            contract_hash=config.contract_hash,
            release_calendar_version=config.release_calendar_version,
            prereg_hash=config.prereg_hash,
        )
        outcome = run_decision_tick(
            context,
            control_params=ControlLawParams(k=config.control_gain),
            adapter_params=AdapterParams(
                reference_risk_5d_usd=config.reference_risk_5d_usd,
                contract_multiplier_bbl=config.contract_multiplier_bbl,
                max_abs_lots=config.max_abs_lots,
            ),
            n_soft=2,
            decay_lambda=0.25,
            ttl=timedelta(days=1),
        )
        decision_record = simulator.record_decision(
            decision=outcome.decision,
            family_forecast_hash=content_hash(outcome.family_forecast),
            forecast_ids=outcome.forecast_ids,
            kill_switch_state=kill_switch.as_dict(),
            emitted_ts=sample.event.ts_event,
        )
        execution_ids = tuple(
            simulator.record_tick(replace(record, decision_id=decision_record.decision_id))
            for record in outcome.ledger_records
        )
        simulator.write_snapshot_receipt(
            decision_ts=sample.event.ts_event,
            decision_id=decision_record.decision_id,
            execution_ids=execution_ids,
            kill_switch_hash=decision_record.kill_switch_hash,
            code_commit=config.code_commit,
            contract_hash=config.contract_hash,
            pit_manifest_hash=forecast.source_manifest_set_hash,
        )
        _write_json(
            forecast_dir / f"{_timestamp_key(sample.event.ts_event)}_forecast.json",
            forecast.model_dump(mode="json"),
        )
        _write_json(
            decision_dir / f"{_timestamp_key(sample.event.ts_event)}_decision.json",
            outcome.decision.model_dump(mode="json"),
        )
        lineage.append(
            {
                "decision_ts": _utc_iso(sample.event.ts_event),
                "symbol": sample.event.symbol,
                "source_row_index": sample.event.source_row_index,
                "source_row_hash": sample.event.source_row_hash,
                "forecast_id": forecast.forecast_id,
                "decision_id": decision_record.decision_id,
                "decision_hash": decision_record.decision_hash,
                "execution_ids": list(execution_ids),
            }
        )
        exposure = outcome.new_exposure
        prior_lots = outcome.target_lots
    _write_json(feature_dir / "source_to_decision_lineage_report.json", lineage)
    return simulator.counts()


def _forecast_for_sample(config: S40ReplayConfig, sample: DecisionSample) -> ForecastV2:
    mu = max(min(sample.realised_return_since_last_tick * 0.10, 0.02), -0.02)
    spread = max(config.market_vol_5d / 4.0, 0.0025)
    quantiles = tuple(mu + spread * x for x in (-2.0, -1.0, -0.25, 0.0, 0.25, 1.0, 2.0))
    return ForecastV2.build_from_view(
        view=_view_for_sample(config, sample),
        family_id=_FAMILY,
        desk_id=_DESK,
        distribution_version="s4_0_recorded_replay_scaffold",
        target_variable=_TARGET_VARIABLE,
        target_horizon=_TARGET_HORIZON,
        decision_unit=DecisionUnit.LOG_RETURN,
        quantile_vector=quantiles,
        calibration_score=1.0,
        calibration_metadata=CalibrationMetadata(
            method="recorded_replay_scaffold",
            baseline_id="S4_0_B0",
            rolling_window_n=0,
            sample_count=0,
        ),
        data_quality_score=1.0,
        valid_until_ts=sample.event.ts_event + timedelta(days=1),
        emitted_ts=sample.event.ts_event,
        prereg_hash=config.prereg_hash,
        code_commit=config.code_commit,
        contract_hash=config.contract_hash,
        release_calendar_version=config.release_calendar_version,
        evidence_pack_ref=config.run_id,
    )


def _view_for_sample(config: S40ReplayConfig, sample: DecisionSample) -> FeatureView:
    payload = {
        "run_id": config.run_id,
        "front_symbol": config.front_symbol,
        "source_row_hash": sample.event.source_row_hash,
        "ts_event": _utc_iso(sample.event.ts_event),
        "price": sample.event.price,
    }
    return FeatureView(
        as_of_ts=sample.event.ts_event,
        family=_FAMILY,
        desk=_DESK,
        specs=(),
        features=payload,
        source_eligibility={},
        missingness={},
        stale_flags={},
        manifest_ids={},
        forward_fill_used={},
        view_hash=_sha256_json(payload),
    )


def _write_run_control(config: S40ReplayConfig, root: Path) -> None:
    _write_json(root / "run_declaration.json", _config_payload(config))
    _write_json(root / "config_snapshot.json", _config_payload(config))
    (root / "stop_go_criteria.md").write_text(
        "Green requires complete evidence, replay verification, restore success, "
        "and no unresolved SEV0/SEV1 exceptions.\n",
        encoding="utf-8",
    )
    shutil.copy2(config.run_control_dir / "no_money_attestation.md", root)


def _write_data_source(config: S40ReplayConfig, root: Path) -> None:
    _write_json(
        root / "data_source_manifest.json",
        {
            "raw_feed_csv": str(config.raw_feed_csv),
            "vendor": config.vendor,
            "dataset": config.dataset,
            "market_depth": config.market_depth,
            "licensed_or_real_data_required": False,
            "source_policy": "local/free/synthetic recorded replay accepted for S4-0",
        },
    )
    for name in (*_REQUIRED_RUN_CONTROL_FILES, *_OPTIONAL_DATA_SOURCE_FILES):
        source = config.run_control_dir / name
        if source.exists():
            shutil.copy2(source, root / name)


def _write_reference_data(config: S40ReplayConfig, root: Path) -> None:
    _write_json(
        root / "contract_selection_receipt.json",
        {
            "front_symbol": config.front_symbol,
            "next_symbol": config.next_symbol,
            "session_start": _utc_iso(config.session_start),
            "session_end": _utc_iso(config.session_end),
            "roll_status": "must be declared from run config or local metadata before run",
            "vendor": config.vendor,
            "dataset": config.dataset,
            "market_depth": config.market_depth,
        },
    )


def _write_raw_evidence(config: S40ReplayConfig, events: list[MarketEvent], root: Path) -> None:
    source_hash = _sha256_file(config.raw_feed_csv)
    _write_json(
        root / "raw_source_manifest.json",
        {
            "raw_feed_csv": str(config.raw_feed_csv),
            "sha256": source_hash,
            "row_count": len(events),
            "raw_copy_retained": config.copy_raw,
        },
    )
    if config.copy_raw:
        shutil.copy2(config.raw_feed_csv, root / "primary_source_raw.csv")


def _write_normalized_events(events: list[MarketEvent], root: Path) -> None:
    path = root / "normalized_events.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ts_event",
                "ts_recv",
                "symbol",
                "price",
                "size",
                "sequence",
                "source_row_index",
                "source_row_hash",
            ],
        )
        writer.writeheader()
        for event in events:
            writer.writerow(
                {
                    "ts_event": _utc_iso(event.ts_event),
                    "ts_recv": _utc_iso(event.ts_recv) if event.ts_recv else "",
                    "symbol": event.symbol,
                    "price": event.price,
                    "size": "" if event.size is None else event.size,
                    "sequence": event.sequence or "",
                    "source_row_index": event.source_row_index,
                    "source_row_hash": event.source_row_hash,
                }
            )
    (root / "raw_to_normalized_mapping.md").write_text(
        "S4-0 scaffold maps recorded-replay CSV columns "
        "`ts_event`, `ts_recv`, `symbol`, `price`, `size`, and `sequence` "
        "into the normalized replay event schema.\n",
        encoding="utf-8",
    )


def _write_data_quality(report: DataQualityReport, events: list[MarketEvent], root: Path) -> None:
    _write_json(root / "data_quality_report.json", _dataclass_payload(report))
    _write_json(root / "timestamp_audit_report.json", _timestamp_audit(events))
    with (root / "gap_duplicate_out_of_order_report.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=["metric", "value"])
        writer.writeheader()
        for key, value in _dataclass_payload(report).items():
            if key != "symbol_counts":
                writer.writerow({"metric": key, "value": value})


def _write_simulation_ledger(simulator: InternalSimulator, root: Path) -> None:
    path = root / "simulated_ledger.csv"
    rows = simulator.conn.execute(
        """
        SELECT decision_id, execution_id, family, decision_ts, scenario, prior_lots,
               new_lots, raw_lots, effective_b, price, market_vol_5d,
               fill_cost, gross_return, net_return, abstain, abstain_reason
        FROM execution_ledger
        ORDER BY decision_ts ASC, scenario ASC
        """
    ).fetchall()
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "decision_id",
                "execution_id",
                "family",
                "decision_ts",
                "scenario",
                "prior_lots",
                "new_lots",
                "raw_lots",
                "effective_b",
                "price",
                "market_vol_5d",
                "fill_cost",
                "gross_return",
                "net_return",
                "abstain",
                "abstain_reason",
            ]
        )
        writer.writerows(rows)
    (root / "simulator_spec.md").write_text(
        "S4-0 uses the v2 internal simulator. This is a no-money simulation "
        "and is not evidence of live execution quality.\n",
        encoding="utf-8",
    )


def _write_runtime_controls(runtime_root: Path, root: Path) -> None:
    kill_switch = runtime_root / "kill_switch.yaml"
    if kill_switch.exists():
        shutil.copy2(kill_switch, root / "kill_switch.yaml")
    else:
        (root / "kill_switch.yaml").write_text("families: {}\n", encoding="utf-8")
    (root / "manual_override_log.csv").write_text(
        "ts,operator,action,reason\n", encoding="utf-8"
    )


def _write_incidents(runtime_root: Path, root: Path) -> None:
    source = runtime_root / "incidents.jsonl"
    if source.exists():
        shutil.copy2(source, root / "incidents.jsonl")
    else:
        (root / "incidents.jsonl").write_text("", encoding="utf-8")
    (root / "incident_register.csv").write_text(
        "incident_id,status,severity,reason\n", encoding="utf-8"
    )


def _write_monitoring(
    config: S40ReplayConfig,
    quality: DataQualityReport,
    runtime_counts: dict[str, int],
    root: Path,
) -> None:
    _write_json(
        root / "uptime_report.json",
        {
            "run_id": config.run_id,
            "session_start": _utc_iso(config.session_start),
            "session_end": _utc_iso(config.session_end),
            "accepted_rows": quality.accepted_rows,
            "decision_count": runtime_counts["family_decisions"],
            "status": "completed",
        },
    )
    (root / "alert_history.csv").write_text(
        "ts,alert,severity,status\n", encoding="utf-8"
    )


def _write_reconciliation(
    quality: DataQualityReport, runtime_counts: dict[str, int], root: Path
) -> None:
    _write_json(
        root / "reconciliation_report.json",
        {
            "raw_to_normalized_rows": {
                "accepted_rows": quality.accepted_rows,
                "normalized_rows": quality.accepted_rows,
            },
            "forecast_to_decision": {
                "forecast_count": runtime_counts["family_decisions"],
                "decision_count": runtime_counts["family_decisions"],
            },
            "decision_to_simulated_execution": {
                "decision_count": runtime_counts["family_decisions"],
                "execution_rows": runtime_counts["execution_ledger"],
            },
        },
    )


def _write_replay_report(verifications: list[SnapshotVerification], root: Path) -> None:
    _write_json(
        root / "replay_verification_report.json",
        {
            "windows": len(verifications),
            "ok": all(item.ok for item in verifications),
            "failures": [
                {
                    "receipt_path": str(item.receipt_path),
                    "checks": [check.name for check in item.failures],
                }
                for item in verifications
                if not item.ok
            ],
        },
    )
    with (root / "replay_differences.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["receipt_path", "check", "expected", "actual", "detail"])
        for item in verifications:
            for check in item.failures:
                writer.writerow(
                    [
                        item.receipt_path,
                        check.name,
                        check.expected,
                        check.actual,
                        check.detail,
                    ]
                )


def _write_restore_summary(
    restore_ok: bool | None, restored_counts: dict[str, int] | None, root: Path
) -> None:
    _write_json(
        root / "restore_summary.json",
        {
            "restore_attempted": restore_ok is not None,
            "restore_ok": restore_ok,
            "restored_counts": restored_counts,
        },
    )


def _write_final_report(
    config: S40ReplayConfig,
    quality: DataQualityReport,
    runtime_counts: dict[str, int],
    stop_go: str,
    exceptions: list[str],
    root: Path,
) -> None:
    report = f"""# {config.stage} run report

- Run ID: `{config.run_id}`
- Stage: `{config.stage}`
- Vendor: `{config.vendor}`
- Dataset: `{config.dataset}`
- Front / next: `{config.front_symbol}` / `{config.next_symbol}`
- Session: `{_utc_iso(config.session_start)}` to `{_utc_iso(config.session_end)}`
- Stop/go: `{stop_go}`

## Metrics

- Accepted replay rows: {quality.accepted_rows}
- Decision count: {runtime_counts["family_decisions"]}
- Execution rows: {runtime_counts["execution_ledger"]}
- Duplicate rows: {quality.duplicate_rows}
- Out-of-order rows: {quality.out_of_order_rows}

## Exceptions

{_markdown_list(exceptions) if exceptions else "- None"}

## Non-Claims

- No real-capital pathway was used.
- This is not a profitability or investment-performance result.
- This is not evidence of live execution quality.
"""
    (root / "final_s4_0_report.md").write_text(report, encoding="utf-8")
    _write_json(root / "stop_go_assessment.json", {"result": stop_go, "exceptions": exceptions})


def _write_manifest(
    config: S40ReplayConfig,
    run_root: Path,
    quality: DataQualityReport,
    runtime_counts: dict[str, int],
    exceptions: list[str],
    stop_go: str,
) -> Path:
    files = []
    for path in sorted(run_root.rglob("*")):
        if not path.is_file() or path.name in {"manifest.yaml", "manifest.sha256"}:
            continue
        files.append(
            {
                "path": str(path.relative_to(run_root)),
                "sha256": _sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    payload = {
        "run_id": config.run_id,
        "stage": config.stage,
        "instrument_family": _FAMILY,
        "session_start": _utc_iso(config.session_start),
        "session_end": _utc_iso(config.session_end),
        "data_source": {"vendor": config.vendor, "dataset": config.dataset},
        "symbols": {"front": config.front_symbol, "next": config.next_symbol},
        "code_commit": config.code_commit,
        "contract_hash": config.contract_hash,
        "record_counts": {
            **_dataclass_payload(quality),
            **runtime_counts,
        },
        "known_exceptions": exceptions,
        "stop_go": stop_go,
        "files": files,
    }
    manifest_path = run_root / "manifest.yaml"
    manifest_text = yaml.safe_dump(payload, sort_keys=True)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    (run_root / "manifest.sha256").write_text(
        hashlib.sha256(manifest_text.encode("utf-8")).hexdigest() + "\n",
        encoding="utf-8",
    )
    return manifest_path


def _timestamp_audit(events: list[MarketEvent]) -> dict[str, Any]:
    latencies = [
        (event.ts_recv - event.ts_event).total_seconds()
        for event in events
        if event.ts_recv is not None
    ]
    ticks = [
        ReplayTick(
            symbol=event.symbol,
            ts_event=event.ts_event,
            ts_recv=event.ts_recv,
            vendor_row_number=event.source_row_index,
            exchange_sequence_number=_parse_sequence(event.sequence),
        )
        for event in events
    ]
    tick_quality = analyze_tick_quality(
        ticks,
        expected_symbols={event.symbol for event in events},
        sequence_scope="global",
    )
    negative_latency = sum(1 for value in latencies if value < 0)
    return {
        "event_ordering_priority": [
            "exchange_sequence_number",
            "ts_event",
            "ts_recv",
            "vendor_row_number",
        ],
        "timestamp_fields": {
            "ts_event": "source event timestamp",
            "ts_recv": "vendor receive/capture timestamp when present",
            "local_normalization_time": "not recorded by S4-0 scaffold",
            "decision_time": "same as selected decision event timestamp",
            "replay_time": "runtime wall-clock replay not used for ordering",
        },
        "rows_with_ts_recv": len(latencies),
        "negative_latency_count": negative_latency,
        "min_latency_seconds": min(latencies) if latencies else None,
        "max_latency_seconds": max(latencies) if latencies else None,
        "tick_quality": tick_quality.as_dict(),
    }


def _stop_go(
    quality: DataQualityReport,
    verifications: list[SnapshotVerification],
    restored_counts: dict[str, int] | None,
    exceptions: list[str],
) -> str:
    if quality.hard_failures or exceptions:
        return "red"
    if any(not verification.ok for verification in verifications):
        return "red"
    if restored_counts is None:
        return "amber"
    if quality.duplicate_rows or quality.out_of_order_rows:
        return "amber"
    return "green"


def _config_payload(config: S40ReplayConfig) -> dict[str, Any]:
    return {
        "run_id": config.run_id,
        "evidence_root": str(config.evidence_root),
        "raw_feed_csv": str(config.raw_feed_csv),
        "run_control_dir": str(config.run_control_dir),
        "front_symbol": config.front_symbol,
        "next_symbol": config.next_symbol,
        "session_start": _utc_iso(config.session_start),
        "session_end": _utc_iso(config.session_end),
        "vendor": config.vendor,
        "dataset": config.dataset,
        "market_depth": config.market_depth,
        "decision_interval_minutes": config.decision_interval_minutes,
        "market_vol_5d": config.market_vol_5d,
        "copy_raw": config.copy_raw,
        "restore_last_snapshot": config.restore_last_snapshot,
        "code_commit": config.code_commit,
        "stage": config.stage,
    }


def _dataclass_payload(value: Any) -> dict[str, Any]:
    return {
        key: getattr(value, key)
        for key in getattr(value, "__dataclass_fields__", {})
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _parse_utc(value: str) -> datetime:
    ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if ts.tzinfo is None:
        raise ValueError(f"timestamp must include timezone: {value!r}")
    return ts.astimezone(UTC)


def _utc_iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_key(ts: datetime) -> str:
    return str(_utc_iso(ts)).replace(":", "")


def _hash_dict(row: dict[str, str]) -> str:
    return _sha256_json({key: row.get(key, "") for key in sorted(row)})


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_sequence(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


if __name__ == "__main__":
    raise SystemExit(main())
