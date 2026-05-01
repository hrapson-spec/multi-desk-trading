"""Operator kill-switch commands for v2 paper-live runtime state."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from v2.runtime.kill_switch import ENABLED, FROZEN, HALTED

_KILL_SWITCH_FILE = "kill_switch.yaml"
_INCIDENTS_FILE = "incidents.jsonl"


class KillctlError(RuntimeError):
    """Raised when a killctl command is invalid."""


@dataclass(frozen=True)
class KillctlResult:
    command: str
    incident_id: str
    kill_switch_path: Path
    incidents_path: Path
    state: dict[str, Any]


def isolate_desk(
    runtime_root: Path,
    *,
    family: str,
    desk: str,
    reason: str,
    evidence: Path,
    severity: str = "sev3",
    now: datetime | None = None,
) -> KillctlResult:
    runtime_root = Path(runtime_root)
    now = _now(now)
    _require_reason(reason)
    evidence_ref = _evidence_ref(evidence)
    state = _load_state(runtime_root)
    incident = _open_incident(
        runtime_root,
        command="isolate",
        scope="desk",
        severity=severity,
        reason=reason,
        evidence_ref=evidence_ref,
        now=now,
        family=family,
        desk=desk,
    )
    family_state = _ensure_family(state, family)
    isolated = set(family_state.get("isolated_desks") or [])
    isolated.add(desk)
    family_state["state"] = family_state.get("state") or ENABLED
    family_state["isolated_desks"] = sorted(isolated)
    family_state["reason"] = reason
    family_state["triggered_at"] = _utc_iso(now)
    family_state["incident_ref"] = incident["incident_id"]
    return _write_result(runtime_root, "isolate", incident["incident_id"], state)


def freeze_family(
    runtime_root: Path,
    *,
    family: str,
    reason: str,
    evidence: Path,
    severity: str = "sev2",
    now: datetime | None = None,
) -> KillctlResult:
    runtime_root = Path(runtime_root)
    now = _now(now)
    _require_reason(reason)
    evidence_ref = _evidence_ref(evidence)
    state = _load_state(runtime_root)
    incident = _open_incident(
        runtime_root,
        command="freeze",
        scope="family",
        severity=severity,
        reason=reason,
        evidence_ref=evidence_ref,
        now=now,
        family=family,
    )
    family_state = _ensure_family(state, family)
    family_state["state"] = FROZEN
    family_state["reason"] = reason
    family_state["triggered_at"] = _utc_iso(now)
    family_state["incident_ref"] = incident["incident_id"]
    return _write_result(runtime_root, "freeze", incident["incident_id"], state)


def halt_system(
    runtime_root: Path,
    *,
    reason: str,
    evidence: Path,
    severity: str = "sev1",
    now: datetime | None = None,
) -> KillctlResult:
    runtime_root = Path(runtime_root)
    now = _now(now)
    _require_reason(reason)
    evidence_ref = _evidence_ref(evidence)
    state = _load_state(runtime_root)
    incident = _open_incident(
        runtime_root,
        command="halt",
        scope="system",
        severity=severity,
        reason=reason,
        evidence_ref=evidence_ref,
        now=now,
    )
    state["system_state"] = HALTED
    state["reason"] = reason
    state["triggered_at"] = _utc_iso(now)
    state["incident_ref"] = incident["incident_id"]
    return _write_result(runtime_root, "halt", incident["incident_id"], state)


def clear_target(
    runtime_root: Path,
    *,
    target: str,
    incident_id: str,
    resolution_evidence: Path,
    now: datetime | None = None,
) -> KillctlResult:
    runtime_root = Path(runtime_root)
    now = _now(now)
    evidence_ref = _evidence_ref(resolution_evidence)
    state = _load_state(runtime_root)
    incident = _latest_incident(runtime_root, incident_id)
    if incident is None:
        raise KillctlError(f"incident {incident_id!r} not found")
    if incident.get("status") == "closed":
        raise KillctlError(f"incident {incident_id!r} is already closed")

    family, desk = _parse_target(target)
    if family == "system":
        state["system_state"] = ENABLED
        state["reason"] = ""
        state["triggered_at"] = None
        state["incident_ref"] = None
    elif desk is not None:
        family_state = _ensure_family(state, family)
        isolated = set(family_state.get("isolated_desks") or [])
        isolated.discard(desk)
        family_state["isolated_desks"] = sorted(isolated)
        if not isolated and family_state.get("state", ENABLED) == ENABLED:
            family_state["reason"] = ""
            family_state["incident_ref"] = None
    else:
        family_state = _ensure_family(state, family)
        isolated = family_state.get("isolated_desks") or []
        if isolated:
            raise KillctlError(
                f"cannot clear family {family!r} while desks remain isolated: {isolated}"
            )
        family_state["state"] = ENABLED
        family_state["reason"] = ""
        family_state["triggered_at"] = None
        family_state["incident_ref"] = None

    _append_incident(
        runtime_root,
        {
            **incident,
            "status": "closed",
            "closed_at": _utc_iso(now),
            "closure_evidence_refs": [evidence_ref],
        },
    )
    return _write_result(runtime_root, "clear", incident_id, state)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="killctl")
    parser.add_argument("--runtime-root", required=True, type=Path)
    sub = parser.add_subparsers(dest="command", required=True)

    isolate = sub.add_parser("isolate")
    isolate.add_argument("target")
    isolate.add_argument("--reason", required=True)
    isolate.add_argument("--evidence", required=True, type=Path)

    freeze = sub.add_parser("freeze")
    freeze.add_argument("family")
    freeze.add_argument("--reason", required=True)
    freeze.add_argument("--evidence", required=True, type=Path)

    halt = sub.add_parser("halt")
    halt.add_argument("--reason", required=True)
    halt.add_argument("--evidence", required=True, type=Path)

    clear = sub.add_parser("clear")
    clear.add_argument("target")
    clear.add_argument("--incident", required=True)
    clear.add_argument("--resolution-evidence", required=True, type=Path)

    args = parser.parse_args(argv)
    if args.command == "isolate":
        family, desk = _parse_target(args.target)
        if desk is None or family == "system":
            raise KillctlError("isolate target must be <family>/<desk>")
        result = isolate_desk(
            args.runtime_root,
            family=family,
            desk=desk,
            reason=args.reason,
            evidence=args.evidence,
        )
    elif args.command == "freeze":
        result = freeze_family(
            args.runtime_root,
            family=args.family,
            reason=args.reason,
            evidence=args.evidence,
        )
    elif args.command == "halt":
        result = halt_system(
            args.runtime_root,
            reason=args.reason,
            evidence=args.evidence,
        )
    else:
        result = clear_target(
            args.runtime_root,
            target=args.target,
            incident_id=args.incident,
            resolution_evidence=args.resolution_evidence,
        )
    print(json.dumps({"incident_id": result.incident_id, "command": result.command}))
    return 0


def _load_state(runtime_root: Path) -> dict[str, Any]:
    path = runtime_root / _KILL_SWITCH_FILE
    if not path.exists():
        return {"system_state": ENABLED, "reason": "", "families": {}}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise KillctlError("kill_switch.yaml must contain a mapping")
    raw.setdefault("system_state", ENABLED)
    raw.setdefault("reason", "")
    raw.setdefault("families", {})
    return raw


def _write_result(
    runtime_root: Path,
    command: str,
    incident_id: str,
    state: dict[str, Any],
) -> KillctlResult:
    runtime_root.mkdir(parents=True, exist_ok=True)
    kill_switch_path = runtime_root / _KILL_SWITCH_FILE
    kill_switch_path.write_text(
        yaml.safe_dump(state, sort_keys=True),
        encoding="utf-8",
    )
    return KillctlResult(
        command=command,
        incident_id=incident_id,
        kill_switch_path=kill_switch_path,
        incidents_path=runtime_root / _INCIDENTS_FILE,
        state=state,
    )


def _ensure_family(state: dict[str, Any], family: str) -> dict[str, Any]:
    families = state.setdefault("families", {})
    family_state = families.setdefault(
        family,
        {
            "state": ENABLED,
            "isolated_desks": [],
            "reason": "",
            "triggered_by": None,
            "triggered_at": None,
            "expires_at": None,
            "incident_ref": None,
        },
    )
    family_state.setdefault("state", ENABLED)
    family_state.setdefault("isolated_desks", [])
    family_state.setdefault("reason", "")
    return family_state


def _open_incident(
    runtime_root: Path,
    *,
    command: str,
    scope: str,
    severity: str,
    reason: str,
    evidence_ref: str,
    now: datetime,
    family: str | None = None,
    desk: str | None = None,
) -> dict[str, Any]:
    incident = {
        "incident_id": _incident_id(runtime_root, now),
        "opened_at": _utc_iso(now),
        "closed_at": None,
        "command": command,
        "scope": scope,
        "family": family,
        "desk": desk,
        "severity": severity,
        "status": "open",
        "reason": reason,
        "evidence_refs": [evidence_ref],
        "closure_evidence_refs": [],
        "post_incident_review_required": severity in {"sev1", "sev2"},
    }
    _append_incident(runtime_root, incident)
    return incident


def _append_incident(runtime_root: Path, incident: dict[str, Any]) -> None:
    runtime_root.mkdir(parents=True, exist_ok=True)
    path = runtime_root / _INCIDENTS_FILE
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(incident, sort_keys=True, separators=(",", ":")) + "\n")


def _latest_incident(runtime_root: Path, incident_id: str) -> dict[str, Any] | None:
    path = runtime_root / _INCIDENTS_FILE
    if not path.exists():
        return None
    latest = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        incident = json.loads(line)
        if incident.get("incident_id") == incident_id:
            latest = incident
    return latest


def _incident_id(runtime_root: Path, now: datetime) -> str:
    prefix = f"inc_{now.strftime('%Y%m%dT%H%M%SZ')}"
    path = runtime_root / _INCIDENTS_FILE
    count = 1
    if path.exists():
        count += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if prefix in line)
    return f"{prefix}_{count:03d}"


def _parse_target(target: str) -> tuple[str, str | None]:
    if target == "system":
        return "system", None
    if "/" in target:
        family, desk = target.split("/", 1)
        if not family or not desk:
            raise KillctlError("target must be <family>/<desk>, <family>, or system")
        return family, desk
    if not target:
        raise KillctlError("target is required")
    return target, None


def _evidence_ref(path: Path) -> str:
    path = Path(path)
    if not path.exists():
        raise KillctlError(f"evidence path does not exist: {path}")
    return str(path)


def _require_reason(reason: str) -> None:
    if not reason.strip():
        raise KillctlError("reason is required")


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)


def _utc_iso(ts: datetime) -> str:
    return _now(ts).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
