"""B10 Phase B dry-run tests."""

from __future__ import annotations

import json

import pytest

from v2.runtime import load_kill_switch
from v2.runtime.dry_run import PhaseBDryRunError, run_phase_b_dry_run


def test_phase_b_dry_run_exercises_runtime_substrate(tmp_path):
    root = tmp_path / "dry-run"

    report = run_phase_b_dry_run(root)

    assert report.ok is True
    assert report.runtime_counts == {"family_decisions": 3, "execution_ledger": 6}
    assert report.restored_counts == {"family_decisions": 1, "execution_ledger": 2}
    assert tuple(step.name for step in report.steps) == (
        "enabled_tick",
        "isolated_tick",
        "frozen_tick",
        "restore_first_snapshot",
    )
    assert len(report.incident_ids) == 2
    state = load_kill_switch(report.runtime_root, family="oil_wti_5d")
    assert state.effective_state("oil_wti_5d") == "enabled"
    assert state.isolated_desks("oil_wti_5d") == ()

    incidents = [
        json.loads(line)
        for line in (report.runtime_root / "incidents.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [incident["status"] for incident in incidents] == [
        "open",
        "closed",
        "open",
        "closed",
    ]
    assert (report.restore_root / "restore_report.json").exists()


def test_phase_b_dry_run_refuses_non_empty_root_without_overwrite(tmp_path):
    root = tmp_path / "dry-run"
    root.mkdir()
    (root / "existing.txt").write_text("occupied\n", encoding="utf-8")

    with pytest.raises(PhaseBDryRunError, match="not empty"):
        run_phase_b_dry_run(root)


def test_phase_b_dry_run_overwrite_replaces_root(tmp_path):
    root = tmp_path / "dry-run"
    root.mkdir()
    (root / "existing.txt").write_text("occupied\n", encoding="utf-8")

    report = run_phase_b_dry_run(root, overwrite=True)

    assert report.ok is True
    assert not (root / "existing.txt").exists()
