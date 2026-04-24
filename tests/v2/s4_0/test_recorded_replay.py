"""S4-0 recorded replay runner tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import yaml

from v2.s4_0.recorded_replay import (
    S40PreflightError,
    S40ReplayConfig,
    main,
    run_s4_0_recorded_replay,
)


def test_s4_0_recorded_replay_writes_reviewer_grade_evidence(tmp_path):
    clearance = _clearance_dir(tmp_path)
    raw = _raw_feed(tmp_path)
    config = S40ReplayConfig(
        run_id="s4_0_wti_20260424_001",
        evidence_root=tmp_path / "evidence",
        raw_feed_csv=raw,
        licence_clearance_dir=clearance,
        front_symbol="CLM6",
        next_symbol="CLN6",
        session_start=datetime(2026, 4, 24, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 4, 24, 16, 0, tzinfo=UTC),
        decision_interval_minutes=60,
    )

    report = run_s4_0_recorded_replay(config)

    assert report.ok is True
    assert report.stop_go == "green"
    assert report.runtime_counts == {"family_decisions": 3, "execution_ledger": 6}
    assert report.restored_counts == {"family_decisions": 3, "execution_ledger": 6}
    assert report.data_quality.front_rows == 4
    assert report.data_quality.next_rows == 2
    assert report.manifest_path.exists()
    assert (report.run_root / "manifest.sha256").exists()
    assert (report.run_root / "03_raw_feed" / "raw_source_manifest.json").exists()
    assert (report.run_root / "04_normalized_feed" / "normalized_events.csv").exists()
    assert (report.run_root / "09_simulation" / "simulated_ledger.csv").exists()
    assert (report.run_root / "14_replay" / "replay_verification_report.json").exists()
    assert (report.run_root / "15_restore" / "restore_summary.json").exists()
    stop_go = json.loads(
        (report.run_root / "16_report" / "stop_go_assessment.json").read_text(
            encoding="utf-8"
        )
    )
    assert stop_go["result"] == "green"


def test_s4_0_recorded_replay_requires_licence_and_no_money_clearance(tmp_path):
    raw = _raw_feed(tmp_path)
    clearance = tmp_path / "clearance"
    clearance.mkdir()
    (clearance / "licence_boundary_table.md").write_text("ok\n", encoding="utf-8")

    config = S40ReplayConfig(
        run_id="s4_0_wti_20260424_001",
        evidence_root=tmp_path / "evidence",
        raw_feed_csv=raw,
        licence_clearance_dir=clearance,
        front_symbol="CLM6",
        next_symbol="CLN6",
        session_start=datetime(2026, 4, 24, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 4, 24, 16, 0, tzinfo=UTC),
    )

    with pytest.raises(S40PreflightError, match="clearance files missing"):
        run_s4_0_recorded_replay(config)


def test_s4_0_recorded_replay_rejects_unapproved_clearance_template(tmp_path):
    raw = _raw_feed(tmp_path)
    clearance = _clearance_dir(tmp_path, approved=False)

    config = S40ReplayConfig(
        run_id="s4_0_wti_20260424_001",
        evidence_root=tmp_path / "evidence",
        raw_feed_csv=raw,
        licence_clearance_dir=clearance,
        front_symbol="CLM6",
        next_symbol="CLN6",
        session_start=datetime(2026, 4, 24, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 4, 24, 16, 0, tzinfo=UTC),
    )

    with pytest.raises(S40PreflightError, match="must explicitly approve"):
        run_s4_0_recorded_replay(config)


def test_s4_0_cli_runs_from_yaml_config(tmp_path, capsys):
    clearance = _clearance_dir(tmp_path)
    raw = _raw_feed(tmp_path)
    config_path = tmp_path / "s4_0.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "run_id": "s4_0_wti_20260424_001",
                "evidence_root": "evidence",
                "raw_feed_csv": str(raw),
                "licence_clearance_dir": str(clearance),
                "front_symbol": "CLM6",
                "next_symbol": "CLN6",
                "session_start": "2026-04-24T13:00:00Z",
                "session_end": "2026-04-24T16:00:00Z",
                "decision_interval_minutes": 60,
            }
        ),
        encoding="utf-8",
    )

    result = main(["--config", str(config_path)])

    assert result == 0
    output = json.loads(capsys.readouterr().out)
    assert output["stop_go"] == "green"
    assert output["runtime_counts"] == {"execution_ledger": 6, "family_decisions": 3}


def test_s4_0f_free_data_stage_label_and_approval_line(tmp_path):
    clearance = _clearance_dir(tmp_path, approval_line="s4_0f")
    raw = _raw_feed(tmp_path)
    config = S40ReplayConfig(
        run_id="s4_0f_wti_free_data_001",
        evidence_root=tmp_path / "evidence",
        raw_feed_csv=raw,
        licence_clearance_dir=clearance,
        front_symbol="CLM6",
        next_symbol="CLN6",
        session_start=datetime(2026, 4, 24, 13, 0, tzinfo=UTC),
        session_end=datetime(2026, 4, 24, 16, 0, tzinfo=UTC),
        decision_interval_minutes=60,
        stage="S4-0F free-data operational rehearsal",
    )

    report = run_s4_0_recorded_replay(config)

    manifest = yaml.safe_load(report.manifest_path.read_text(encoding="utf-8"))
    final_report = (
        report.run_root / "16_report" / "final_s4_0_report.md"
    ).read_text(encoding="utf-8")
    assert report.ok is True
    assert manifest["stage"] == "S4-0F free-data operational rehearsal"
    assert "# S4-0F free-data operational rehearsal run report" in final_report


def _clearance_dir(tmp_path, *, approved: bool = True, approval_line: str = "s4_0"):
    root = tmp_path / "clearance"
    root.mkdir()
    (root / "licence_boundary_table.md").write_text(
        "licence_boundary_table.md: cleared for test fixture\n", encoding="utf-8"
    )
    (root / "vendor_terms_summary.md").write_text(
        "vendor_terms_summary.md: cleared for test fixture\n", encoding="utf-8"
    )
    approval_text = (
        "Approved for S4-0F no-money free-data rehearsal execution."
        if approval_line == "s4_0f"
        else "Approved for S4-0 no-money recorded replay execution."
    )
    owner_line = f"- [{'x' if approved else ' '}] {approval_text}"
    (root / "owner_clearance_decision.md").write_text(
        f"{owner_line}\n- [ ] Not approved; blocker remains.\n",
        encoding="utf-8",
    )
    checked = "[x]" if approved else "[ ]"
    (root / "no_money_attestation.md").write_text(
        "\n".join(
            [
                f"- {checked} No live broker route is configured.",
                f"- {checked} No funded account is connected.",
                f"- {checked} No live order API key is present in the run environment.",
                f"- {checked} Execution is internal simulation only.",
                f"- {checked} Any paper/live brokerage integration is out of scope for this run.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return root


def _raw_feed(tmp_path):
    path = tmp_path / "databento_cl_fixture.csv"
    path.write_text(
        "\n".join(
            [
                "ts_event,ts_recv,symbol,price,size,sequence",
                "2026-04-24T13:10:00Z,2026-04-24T13:10:00.000001Z,CLM6,75.00,10,1",
                "2026-04-24T13:15:00Z,2026-04-24T13:15:00.000001Z,CLN6,74.80,8,2",
                "2026-04-24T14:10:00Z,2026-04-24T14:10:00.000001Z,CLM6,75.20,12,3",
                "2026-04-24T14:15:00Z,2026-04-24T14:15:00.000001Z,CLN6,75.00,9,4",
                "2026-04-24T15:05:00Z,2026-04-24T15:05:00.000001Z,CLM6,75.10,11,5",
                "2026-04-24T15:40:00Z,2026-04-24T15:40:00.000001Z,CLM6,75.30,10,6",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path
