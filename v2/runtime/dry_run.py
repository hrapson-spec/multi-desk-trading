"""Phase-B operational dry-run harness.

This harness exercises the completed runtime substrate without live feeds
or broker integration. It is deterministic and uses an internal scaffold
desk so it can run in CI and as a local closeout check.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from v2.contracts.decision_unit import DecisionUnit
from v2.contracts.decision_v2 import DegradationState
from v2.contracts.forecast_v2 import CalibrationMetadata, ForecastV2
from v2.execution.adapter import AdapterParams
from v2.execution.control_law import ControlLawParams
from v2.execution.simulator import InternalSimulator
from v2.feature_view.view import FeatureView
from v2.paper_live.loop import PaperLiveLoop
from v2.runtime.killctl import clear_target, freeze_family, isolate_desk
from v2.runtime.replay import verify_snapshot_receipt
from v2.runtime.restore import restore_runtime_snapshot

_FAMILY = "oil_wti_5d"
_DESK = "dry_run_desk"
_CONTRACT_HASH = "sha256:dry-run-contract"
_PREREG_HASH = "sha256:dry-run-prereg"
_CODE_COMMIT = "dry-run"
_RELEASE_CALENDAR_VERSION = "dry-run-calendar:1.0.0"
_BASE_TS = datetime(2026, 4, 22, 21, 0, tzinfo=UTC)
_OP_TS = datetime(2026, 4, 24, 9, 30, tzinfo=UTC)


@dataclass(frozen=True)
class DryRunStep:
    name: str
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class PhaseBDryRunReport:
    root: Path
    runtime_root: Path
    restore_root: Path
    runtime_counts: dict[str, int]
    restored_counts: dict[str, int]
    incident_ids: tuple[str, ...]
    steps: tuple[DryRunStep, ...]

    @property
    def ok(self) -> bool:
        return all(step.passed for step in self.steps)


class PhaseBDryRunError(RuntimeError):
    """Raised when the dry-run root cannot be prepared safely."""


def run_phase_b_dry_run(root: Path, *, overwrite: bool = False) -> PhaseBDryRunReport:
    """Run the deterministic Phase-B operational dry-run."""
    root = Path(root)
    if root.exists() and any(root.iterdir()):
        if not overwrite:
            raise PhaseBDryRunError(f"dry-run root is not empty: {root}")
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)

    runtime_root = root / "runtime"
    pit_root = root / "pit"
    restore_root = root / "restored"
    evidence_root = root / "evidence"
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence = _write_evidence(evidence_root, "evidence.md")
    resolution = _write_evidence(evidence_root, "resolution.md")

    steps: list[DryRunStep] = []
    incident_ids: list[str] = []
    simulator = InternalSimulator.open(runtime_root)
    loop = _loop(pit_root, simulator)
    try:
        first = _BASE_TS
        first_outcome = loop.tick(
            decision_ts=first,
            emitted_ts=first,
            price=75.0,
            realised_return_since_last_tick=0.01,
            market_vol_5d=0.04,
        )
        first_verify = verify_snapshot_receipt(simulator, decision_ts=first)
        steps.append(
            DryRunStep(
                "enabled_tick",
                first_outcome.decision.abstain is False and first_verify.ok,
            )
        )

        isolated = isolate_desk(
            runtime_root,
            family=_FAMILY,
            desk=_DESK,
            reason="dry-run isolation drill",
            evidence=evidence,
            now=_OP_TS,
        )
        incident_ids.append(isolated.incident_id)
        second = first + timedelta(days=1)
        isolated_outcome = loop.tick(
            decision_ts=second,
            emitted_ts=second,
            price=76.0,
            realised_return_since_last_tick=0.0,
            market_vol_5d=0.04,
        )
        second_verify = verify_snapshot_receipt(simulator, decision_ts=second)
        steps.append(
            DryRunStep(
                "isolated_tick",
                isolated_outcome.decision.abstain is True and second_verify.ok,
                isolated_outcome.decision.abstain_reason or "",
            )
        )
        clear_target(
            runtime_root,
            target=f"{_FAMILY}/{_DESK}",
            incident_id=isolated.incident_id,
            resolution_evidence=resolution,
            now=_OP_TS + timedelta(minutes=1),
        )

        frozen = freeze_family(
            runtime_root,
            family=_FAMILY,
            reason="dry-run freeze drill",
            evidence=evidence,
            now=_OP_TS + timedelta(minutes=2),
        )
        incident_ids.append(frozen.incident_id)
        third = first + timedelta(days=2)
        frozen_outcome = loop.tick(
            decision_ts=third,
            emitted_ts=third,
            price=77.0,
            realised_return_since_last_tick=0.0,
            market_vol_5d=0.04,
        )
        third_verify = verify_snapshot_receipt(simulator, decision_ts=third)
        steps.append(
            DryRunStep(
                "frozen_tick",
                frozen_outcome.new_exposure.state == DegradationState.HARD_FAIL
                and third_verify.ok,
                frozen_outcome.decision.abstain_reason or "",
            )
        )
        clear_target(
            runtime_root,
            target=_FAMILY,
            incident_id=frozen.incident_id,
            resolution_evidence=resolution,
            now=_OP_TS + timedelta(minutes=3),
        )

        restore_report = restore_runtime_snapshot(
            simulator,
            target_runtime_root=restore_root,
            decision_ts=first,
        )
        steps.append(DryRunStep("restore_first_snapshot", restore_report.ok))
        runtime_counts = simulator.counts()
        restored = InternalSimulator.open(restore_root)
        try:
            restored_counts = restored.counts()
        finally:
            restored.close()
    finally:
        loop.close()
        simulator.close()

    return PhaseBDryRunReport(
        root=root,
        runtime_root=runtime_root,
        restore_root=restore_root,
        runtime_counts=runtime_counts,
        restored_counts=restored_counts,
        incident_ids=tuple(incident_ids),
        steps=tuple(steps),
    )


class _DryRunDesk:
    family_id = _FAMILY
    desk_id = _DESK

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
        emitted = emitted_ts or view.as_of_ts
        return ForecastV2.build_from_view(
            view=_empty_view(view.as_of_ts),
            family_id=_FAMILY,
            desk_id=_DESK,
            distribution_version="dry-run",
            target_variable="WTI_FRONT_1W_LOG_RETURN",
            target_horizon="5d",
            decision_unit=DecisionUnit.LOG_RETURN,
            quantile_vector=(-0.08, -0.04, -0.01, 0.008, 0.02, 0.05, 0.09),
            calibration_score=1.0,
            calibration_metadata=CalibrationMetadata(
                method="dry_run",
                baseline_id="B0",
                rolling_window_n=0,
                sample_count=0,
            ),
            data_quality_score=1.0,
            valid_until_ts=view.as_of_ts + timedelta(days=1),
            emitted_ts=emitted,
            prereg_hash=prereg_hash,
            code_commit=code_commit,
            contract_hash=contract_hash,
            release_calendar_version=release_calendar_version,
        )


def _loop(pit_root: Path, simulator: InternalSimulator) -> PaperLiveLoop:
    return PaperLiveLoop(
        pit_root=pit_root,
        family=_FAMILY,
        desks=[_DryRunDesk()],
        simulator=simulator,
        control_params=ControlLawParams(k=1.0),
        adapter_params=AdapterParams(
            reference_risk_5d_usd=100_000.0,
            contract_multiplier_bbl=1_000.0,
        ),
        n_soft=2,
        decay_lambda=0.25,
        ttl=timedelta(days=1),
        contract_hash=_CONTRACT_HASH,
        release_calendar_version=_RELEASE_CALENDAR_VERSION,
        prereg_hash=_PREREG_HASH,
        code_commit=_CODE_COMMIT,
    )


def _empty_view(decision_ts: datetime) -> FeatureView:
    return FeatureView(
        as_of_ts=decision_ts,
        family=_FAMILY,
        desk=_DESK,
        specs=(),
        features={},
        source_eligibility={},
        missingness={},
        stale_flags={},
        manifest_ids={},
        forward_fill_used={},
        view_hash=f"dry-run:{decision_ts.isoformat()}",
    )


def _write_evidence(root: Path, name: str) -> Path:
    path = root / name
    path.write_text("dry-run evidence\n", encoding="utf-8")
    return path
