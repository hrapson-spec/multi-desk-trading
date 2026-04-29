"""Feature-layer admissibility and quality propagation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from v2.feature_view.spec import FeatureSpec
from v2.pit_store.quality import (
    VintageQuality,
    coerce_vintage_quality,
    is_degraded,
    worst_vintage_quality,
)

if TYPE_CHECKING:
    from v2.feature_view.view import FeatureView


class FeatureAdmissibilityError(Exception):
    """Raised when a feature attempts to use inadmissible vintage quality."""


_PROHIBITED_QUALITIES = {
    VintageQuality.LATEST_SNAPSHOT_NOT_PIT,
    VintageQuality.CALENDAR_ONLY_REJECTED,
}

_REVISION_UNKNOWN_FORBIDDEN_USES = {
    "inventory_surprise_magnitude",
    "stock_change_feature",
}


def input_key(source: str, dataset: str | None, series: str | None) -> str:
    parts = [source]
    if dataset:
        parts.append(dataset)
    if series:
        parts.append(series)
    return "/".join(parts)


def enforce_feature_admissibility(spec: FeatureSpec, vintage_quality: str) -> None:
    quality = coerce_vintage_quality(vintage_quality)
    if not spec.enforce_feature_admissibility:
        return
    key = input_key(spec.source, spec.dataset, spec.series)
    if quality in _PROHIBITED_QUALITIES:
        raise FeatureAdmissibilityError(
            f"feature {spec.name!r} cannot use {key}: vintage_quality={quality.value}"
        )
    if (
        quality == VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN
        and spec.feature_use in _REVISION_UNKNOWN_FORBIDDEN_USES
    ):
        raise FeatureAdmissibilityError(
            f"feature {spec.name!r} cannot use {key} for {spec.feature_use}: "
            f"vintage_quality={quality.value}"
        )


@dataclass(frozen=True)
class DataQualityManifest:
    data_quality_warning: bool
    worst_vintage_quality: str
    degraded_inputs: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "data_quality_warning": self.data_quality_warning,
            "worst_vintage_quality": self.worst_vintage_quality,
            "degraded_inputs": list(self.degraded_inputs),
        }


def build_data_quality_manifest(view: FeatureView) -> DataQualityManifest:
    return DataQualityManifest(
        data_quality_warning=view.data_quality_warning,
        worst_vintage_quality=view.worst_vintage_quality,
        degraded_inputs=view.degraded_inputs,
    )


def render_data_quality_warning_block(view: FeatureView) -> str:
    manifest = build_data_quality_manifest(view)
    if not manifest.data_quality_warning:
        return "Data quality: all admitted inputs are true_first_release."
    degraded = ", ".join(manifest.degraded_inputs)
    return (
        "Data quality warning: admitted degraded PIT inputs present. "
        f"worst_vintage_quality={manifest.worst_vintage_quality}; "
        f"degraded_inputs={degraded}"
    )


def summarise_vintage_quality(
    qualities_by_feature: dict[str, str],
    degraded_inputs: set[str],
) -> tuple[str, bool, tuple[str, ...]]:
    worst = worst_vintage_quality(qualities_by_feature.values()).value
    warning = any(is_degraded(q) for q in qualities_by_feature.values())
    return worst, warning, tuple(sorted(degraded_inputs))
