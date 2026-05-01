"""Kill-switch reader for the v2 paper-live loop.

The kill-switch is intentionally a small runtime YAML file outside the
PIT store. Missing files default to fully enabled, so a local dry run can
start without operational configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ENABLED = "enabled"
DESK_ISOLATED = "desk_isolated"
FROZEN = "frozen"
HALTED = "halted"
HALTING_STATES = {FROZEN, HALTED}


@dataclass(frozen=True)
class FamilyKillSwitchState:
    state: str = ENABLED
    isolated_desks: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""
    triggered_by: str | None = None
    triggered_at: str | None = None
    expires_at: str | None = None
    incident_ref: str | None = None

    @property
    def is_halting(self) -> bool:
        return self.state in HALTING_STATES

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "isolated_desks": list(self.isolated_desks),
            "reason": self.reason,
            "triggered_by": self.triggered_by,
            "triggered_at": self.triggered_at,
            "expires_at": self.expires_at,
            "incident_ref": self.incident_ref,
        }


@dataclass(frozen=True)
class KillSwitchState:
    system_state: str = ENABLED
    system_reason: str = ""
    families: dict[str, FamilyKillSwitchState] = field(default_factory=dict)

    @property
    def system_halting(self) -> bool:
        return self.system_state in HALTING_STATES

    def family_state(self, family: str) -> FamilyKillSwitchState:
        return self.families.get(family, FamilyKillSwitchState())

    def effective_state(self, family: str) -> str:
        if self.system_halting:
            return self.system_state
        return self.family_state(family).state

    def is_halting(self, family: str) -> bool:
        return self.system_halting or self.family_state(family).is_halting

    def isolated_desks(self, family: str) -> tuple[str, ...]:
        if self.system_halting:
            return ()
        return self.family_state(family).isolated_desks

    def reason(self, family: str) -> str:
        family_state = self.family_state(family)
        if self.system_halting:
            return self.system_reason or family_state.reason or self.system_state
        return family_state.reason or family_state.state

    def as_dict(self) -> dict[str, Any]:
        return {
            "system_state": self.system_state,
            "system_reason": self.system_reason,
            "families": {
                family: state.as_dict()
                for family, state in sorted(self.families.items(), key=lambda item: item[0])
            },
        }


def load_kill_switch(runtime_root: Path, *, family: str | None = None) -> KillSwitchState:
    """Load `runtime_root/kill_switch.yaml`.

    If the file is absent, return the enabled default. If `family` is
    supplied, the returned object always contains that family key.
    """
    path = Path(runtime_root) / "kill_switch.yaml"
    if not path.exists():
        return _default_state(family)

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("kill_switch.yaml must contain a mapping")

    families_raw = raw.get("families") or {}
    if not isinstance(families_raw, dict):
        raise ValueError("kill_switch.yaml families must be a mapping")

    families = {
        str(name): _parse_family_state(value)
        for name, value in families_raw.items()
        if isinstance(value, dict)
    }
    if family is not None and family not in families:
        families[family] = FamilyKillSwitchState()

    return KillSwitchState(
        system_state=_normalise_state(raw.get("system_state", ENABLED)),
        system_reason=str(raw.get("reason") or raw.get("system_reason") or ""),
        families=families,
    )


def _default_state(family: str | None) -> KillSwitchState:
    families = {family: FamilyKillSwitchState()} if family is not None else {}
    return KillSwitchState(system_state=ENABLED, families=families)


def _parse_family_state(raw: dict[str, Any]) -> FamilyKillSwitchState:
    isolated = raw.get("isolated_desks") or []
    if not isinstance(isolated, list):
        raise ValueError("isolated_desks must be a list")
    return FamilyKillSwitchState(
        state=_normalise_state(raw.get("state", ENABLED)),
        isolated_desks=tuple(str(desk) for desk in isolated),
        reason=str(raw.get("reason") or ""),
        triggered_by=_optional_str(raw.get("triggered_by")),
        triggered_at=_optional_str(raw.get("triggered_at")),
        expires_at=_optional_str(raw.get("expires_at")),
        incident_ref=_optional_str(raw.get("incident_ref")),
    )


def _normalise_state(value: object) -> str:
    state = str(value or ENABLED).strip().lower()
    if state not in {ENABLED, DESK_ISOLATED, FROZEN, HALTED}:
        raise ValueError(f"unknown kill-switch state {state!r}")
    return state


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
