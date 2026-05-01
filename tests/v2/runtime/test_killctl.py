"""B9 killctl operator command tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from v2.governance.killctl import main as cli_main
from v2.runtime import (
    KillctlError,
    clear_target,
    freeze_family,
    halt_system,
    isolate_desk,
    load_kill_switch,
)

FAMILY = "oil_wti_5d"
NOW = datetime(2026, 4, 24, 9, 0, tzinfo=UTC)


def test_isolate_desk_writes_kill_switch_and_incident(tmp_path):
    evidence = _evidence(tmp_path)

    result = isolate_desk(
        tmp_path,
        family=FAMILY,
        desk="desk_a",
        reason="bad data",
        evidence=evidence,
        now=NOW,
    )

    state = load_kill_switch(tmp_path, family=FAMILY)
    assert state.isolated_desks(FAMILY) == ("desk_a",)
    assert state.is_halting(FAMILY) is False
    assert result.incident_id == "inc_20260424T090000Z_001"
    incident = _incidents(tmp_path)[0]
    assert incident["scope"] == "desk"
    assert incident["status"] == "open"


def test_freeze_family_sets_halting_family_state(tmp_path):
    evidence = _evidence(tmp_path)

    result = freeze_family(
        tmp_path,
        family=FAMILY,
        reason="operator freeze",
        evidence=evidence,
        now=NOW,
    )

    state = load_kill_switch(tmp_path, family=FAMILY)
    assert state.effective_state(FAMILY) == "frozen"
    assert state.is_halting(FAMILY) is True
    assert state.reason(FAMILY) == "operator freeze"
    assert result.incident_id == "inc_20260424T090000Z_001"


def test_halt_system_sets_system_halting_state(tmp_path):
    evidence = _evidence(tmp_path)

    result = halt_system(
        tmp_path,
        reason="global stop",
        evidence=evidence,
        now=NOW,
    )

    state = load_kill_switch(tmp_path, family=FAMILY)
    assert state.effective_state(FAMILY) == "halted"
    assert state.is_halting(FAMILY) is True
    assert state.reason(FAMILY) == "global stop"
    assert result.incident_id == "inc_20260424T090000Z_001"


def test_clear_desk_removes_isolation_and_closes_incident(tmp_path):
    evidence = _evidence(tmp_path)
    resolution = _evidence(tmp_path, "resolution.md")
    opened = isolate_desk(
        tmp_path,
        family=FAMILY,
        desk="desk_a",
        reason="bad data",
        evidence=evidence,
        now=NOW,
    )

    clear_target(
        tmp_path,
        target=f"{FAMILY}/desk_a",
        incident_id=opened.incident_id,
        resolution_evidence=resolution,
        now=NOW,
    )

    state = load_kill_switch(tmp_path, family=FAMILY)
    assert state.isolated_desks(FAMILY) == ()
    incidents = _incidents(tmp_path)
    assert incidents[-1]["incident_id"] == opened.incident_id
    assert incidents[-1]["status"] == "closed"
    assert incidents[-1]["closure_evidence_refs"] == [str(resolution)]


def test_clear_family_refuses_while_desks_remain_isolated(tmp_path):
    evidence = _evidence(tmp_path)
    resolution = _evidence(tmp_path, "resolution.md")
    opened = isolate_desk(
        tmp_path,
        family=FAMILY,
        desk="desk_a",
        reason="bad data",
        evidence=evidence,
        now=NOW,
    )

    with pytest.raises(KillctlError, match="desks remain isolated"):
        clear_target(
            tmp_path,
            target=FAMILY,
            incident_id=opened.incident_id,
            resolution_evidence=resolution,
            now=NOW,
        )


def test_cli_isolate_and_clear(tmp_path, capsys):
    evidence = _evidence(tmp_path)
    resolution = _evidence(tmp_path, "resolution.md")

    assert (
        cli_main(
            [
                "--runtime-root",
                str(tmp_path),
                "isolate",
                f"{FAMILY}/desk_a",
                "--reason",
                "bad data",
                "--evidence",
                str(evidence),
            ]
        )
        == 0
    )
    incident_id = json.loads(capsys.readouterr().out)["incident_id"]
    assert (
        cli_main(
            [
                "--runtime-root",
                str(tmp_path),
                "clear",
                f"{FAMILY}/desk_a",
                "--incident",
                incident_id,
                "--resolution-evidence",
                str(resolution),
            ]
        )
        == 0
    )
    assert load_kill_switch(tmp_path, family=FAMILY).isolated_desks(FAMILY) == ()


def test_missing_evidence_is_rejected(tmp_path):
    with pytest.raises(KillctlError, match="evidence path does not exist"):
        halt_system(
            tmp_path,
            reason="global stop",
            evidence=tmp_path / "missing.md",
            now=NOW,
        )


def _evidence(tmp_path, name: str = "evidence.md"):
    path = tmp_path / name
    path.write_text("evidence\n", encoding="utf-8")
    return path


def _incidents(tmp_path):
    return [
        json.loads(line)
        for line in (tmp_path / "incidents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
