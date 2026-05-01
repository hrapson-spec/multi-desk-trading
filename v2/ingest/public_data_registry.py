"""Pydantic-validated catalogue of public data sources for v2 WTI desks.

Single source of truth for:
- which series are model-eligible (``model_eligible=True``),
- their rights status (``public`` / ``display_only`` / ``manual_only`` / ``restricted``),
- retrieval method, frequency, history start, release-calendar reference.

The hard rights-gate invariant: any entry whose ``rights_status`` is not
``"public"`` MUST have ``model_eligible=False``. The Pydantic validator
enforces this at construction time so the YAML cannot drift.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, HttpUrl, ValidationError, field_validator, model_validator

RetrievalMethod = Literal[
    "api", "csv_download", "xlsx_download", "html_scrape", "manual_event_feature"
]
RightsStatus = Literal["public", "display_only", "manual_only", "restricted"]
Frequency = Literal["daily", "weekly", "biweekly", "monthly", "quarterly", "irregular"]


DEFAULT_REGISTRY_PATH = Path(__file__).parent / "registry" / "public_data_inventory.yaml"


class RegistryEntry(BaseModel):
    """A single registered public data series."""

    key: str = Field(..., description="Unique identifier within the registry")
    source: str
    dataset: str | None = None
    series_id: str | None = None
    description: str
    source_url: HttpUrl
    retrieval_method: RetrievalMethod
    rights_status: RightsStatus
    model_eligible: bool
    frequency: Frequency
    history_start: date | None = None
    release_calendar_ref: str | None = Field(
        None, description="Filename within v2/pit_store/calendars/"
    )
    notes: str | None = None

    @field_validator("key", "source", "description")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be non-empty")
        return v

    @model_validator(mode="after")
    def _enforce_rights_gate(self) -> RegistryEntry:
        """Rights-gate invariant: non-public sources cannot be model-eligible."""
        if self.rights_status != "public" and self.model_eligible:
            raise ValueError(
                f"rights-gate violation: entry {self.key!r} has rights_status="
                f"{self.rights_status!r} but model_eligible=True; "
                "only rights_status='public' may be model-eligible"
            )
        return self


class PublicDataRegistry(BaseModel):
    """Top-level registry: a list of entries with unique keys."""

    entries: list[RegistryEntry]

    @model_validator(mode="after")
    def _unique_keys(self) -> PublicDataRegistry:
        seen: set[str] = set()
        for e in self.entries:
            if e.key in seen:
                raise ValueError(f"duplicate registry key: {e.key!r}")
            seen.add(e.key)
        return self


def load_registry(path: Path | None = None) -> PublicDataRegistry:
    """Load and validate the public-data registry from YAML."""
    if path is None:
        path = DEFAULT_REGISTRY_PATH
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    if not isinstance(raw, dict) or "entries" not in raw:
        raise ValidationError.from_exception_data(
            "PublicDataRegistry",
            [{"type": "missing", "loc": ("entries",), "input": raw}],
        )
    return PublicDataRegistry.model_validate(raw)


def eligible_for_model(reg: PublicDataRegistry) -> list[RegistryEntry]:
    """Return only the entries flagged as model-eligible."""
    return [e for e in reg.entries if e.model_eligible]


def entries_for_source(reg: PublicDataRegistry, source: str) -> list[RegistryEntry]:
    """Return entries filtered by ``source`` (exact match)."""
    return [e for e in reg.entries if e.source == source]
