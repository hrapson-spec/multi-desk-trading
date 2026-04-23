"""FeatureView: frozen result object produced by build_feature_view()."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from v2.contracts.forecast_v2 import SourceEligibility
from v2.feature_view.spec import FeatureSpec


@dataclass(frozen=True)
class FeatureView:
    as_of_ts: datetime
    family: str
    desk: str
    specs: tuple[FeatureSpec, ...]
    features: dict[str, Any]
    source_eligibility: dict[str, SourceEligibility]
    missingness: dict[str, bool]  # feature_name -> True if missing
    stale_flags: dict[str, str]  # feature_name -> freshness_state
    manifest_ids: dict[str, str | None]  # feature_name -> vintage manifest_id used
    forward_fill_used: dict[str, bool]  # feature_name -> True iff transform forward-filled
    view_hash: str

    @property
    def any_required_missing(self) -> bool:
        required_names = {s.name for s in self.specs if s.required}
        return any(self.missingness.get(n, False) for n in required_names)

    @property
    def min_quality_multiplier(self) -> float:
        if not self.source_eligibility:
            return 1.0
        return min(e.quality_multiplier for e in self.source_eligibility.values())

    def features_summary(self) -> dict[str, dict]:
        """Small dict suitable for logging / evidence-pack serialisation."""
        return {
            name: {
                "missing": self.missingness.get(name, False),
                "stale": self.stale_flags.get(name),
                "manifest_id": self.manifest_ids.get(name),
            }
            for name in (s.name for s in self.specs)
        }


def empty_eligibility() -> dict[str, SourceEligibility]:
    return {}


def empty_missingness() -> dict[str, bool]:
    return {}


# Forward-ref-compatible builder aliases (unused at module load).
_ = field
