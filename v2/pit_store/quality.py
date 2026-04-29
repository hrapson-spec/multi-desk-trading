"""Vintage-quality contract for PIT data.

The enum is deliberately string-based so values survive DuckDB, Parquet,
JSON manifests, and Markdown reports without custom codecs.
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum


class VintageQuality(StrEnum):
    TRUE_FIRST_RELEASE = "true_first_release"
    RELEASE_LAG_SAFE_REVISION_UNKNOWN = "release_lag_safe_revision_unknown"
    LATEST_SNAPSHOT_NOT_PIT = "latest_snapshot_not_pit"
    CALENDAR_ONLY_REJECTED = "calendar_only_rejected"


_QUALITY_RANK: dict[VintageQuality, int] = {
    VintageQuality.TRUE_FIRST_RELEASE: 0,
    VintageQuality.RELEASE_LAG_SAFE_REVISION_UNKNOWN: 1,
    VintageQuality.LATEST_SNAPSHOT_NOT_PIT: 2,
    VintageQuality.CALENDAR_ONLY_REJECTED: 3,
}


def coerce_vintage_quality(value: str | VintageQuality) -> VintageQuality:
    if isinstance(value, VintageQuality):
        return value
    try:
        return VintageQuality(str(value))
    except ValueError as exc:
        allowed = ", ".join(q.value for q in VintageQuality)
        raise ValueError(f"unknown vintage_quality {value!r}; allowed: {allowed}") from exc


def worst_vintage_quality(values: Iterable[str | VintageQuality]) -> VintageQuality:
    qualities = [coerce_vintage_quality(v) for v in values]
    if not qualities:
        return VintageQuality.TRUE_FIRST_RELEASE
    return max(qualities, key=lambda q: _QUALITY_RANK[q])


def is_degraded(value: str | VintageQuality) -> bool:
    return coerce_vintage_quality(value) != VintageQuality.TRUE_FIRST_RELEASE
