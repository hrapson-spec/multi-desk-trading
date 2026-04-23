"""build_feature_view: (as_of_ts, specs, reader) -> FeatureView.

Determinism contract: given identical `as_of_ts`, identical specs, and
a PIT manifest with identical checksums on the vintages that match,
the resulting `view_hash` is identical regardless of machine or wall
clock. Rationale: the hash is the receipt ForecastV2 carries into the
promotion evidence pack.

Transform registry: at v2.0 we ship `identity` only. Further transforms
(weekly_diff, rolling_mean, calendar_spread) land alongside the first
real ingesters.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from v2.contracts.forecast_v2 import SourceEligibility
from v2.feature_view.spec import FeatureSpec
from v2.feature_view.view import FeatureView
from v2.pit_store.reader import PITReader

TransformFn = Callable[[pd.DataFrame, dict], Any]


class FeatureViewBuildError(Exception):
    """A non-recoverable error constructing a FeatureView."""


def identity_transform(df: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    """Pass-through. Returned DataFrame is the raw vintage."""
    return df


_BUILTIN_TRANSFORMS: dict[str, TransformFn] = {
    "identity": identity_transform,
}


def build_feature_view(
    *,
    as_of_ts: datetime,
    family: str,
    desk: str,
    specs: list[FeatureSpec],
    reader: PITReader,
    transforms: dict[str, TransformFn] | None = None,
) -> FeatureView:
    if as_of_ts.tzinfo is None:
        raise FeatureViewBuildError("as_of_ts must be timezone-aware (UTC)")
    as_of_ts = as_of_ts.astimezone(UTC)

    reg = {**_BUILTIN_TRANSFORMS, **(transforms or {})}

    features: dict[str, Any] = {}
    source_eligibility: dict[str, SourceEligibility] = {}
    missingness: dict[str, bool] = {}
    stale_flags: dict[str, str] = {}
    manifest_ids: dict[str, str | None] = {}
    forward_fill_used: dict[str, bool] = {}

    # Hash inputs: the set of (feature_name, source, series, transform,
    # transform_params, vintage_checksum, eligible, quality_multiplier)
    # tuples the view was built from. Sorted by feature_name for
    # determinism.
    hash_payload: list[dict] = []

    for spec in specs:
        if spec.transform not in reg:
            raise FeatureViewBuildError(
                f"feature {spec.name!r}: transform {spec.transform!r} not registered"
            )

        read = reader.as_of(spec.source, spec.series, as_of_ts)
        if read is None:
            features[spec.name] = None
            missingness[spec.name] = True
            stale_flags[spec.name] = "missing"
            manifest_ids[spec.name] = None
            forward_fill_used[spec.name] = False
            hash_payload.append(
                {
                    "feature": spec.name,
                    "canonical": list(spec.canonical_key()),
                    "vintage_checksum": None,
                    "eligible": False,
                    "quality_multiplier": 0.0,
                }
            )
            continue

        value = reg[spec.transform](read.data, dict(spec.transform_params))
        features[spec.name] = value
        missingness[spec.name] = False
        stale_flags[spec.name] = read.data_quality.freshness_state
        manifest_ids[spec.name] = read.manifest.manifest_id
        # Forward-fill tracking: v2.0 builds do not forward-fill (identity
        # transform only). A future transform that fills gaps must set
        # forward_fill_used=True via the TransformFn contract.
        forward_fill_used[spec.name] = False

        elig = SourceEligibility(
            source=spec.source,
            eligible=read.data_quality.decision_eligible,
            release_lag_days=read.data_quality.release_lag_days,
            freshness_state=read.data_quality.freshness_state,
            quality_multiplier=read.data_quality.quality_multiplier,
            manifest_id=read.manifest.manifest_id,
        )
        # Per-source record. If two specs share a source, the most
        # restrictive quality_multiplier wins; that is a v2.1 refinement
        # and not required at v2.0 — first-write-wins here.
        source_eligibility.setdefault(spec.source, elig)

        hash_payload.append(
            {
                "feature": spec.name,
                "canonical": list(spec.canonical_key()),
                "vintage_checksum": read.manifest.checksum,
                "eligible": read.data_quality.decision_eligible,
                "quality_multiplier": read.data_quality.quality_multiplier,
            }
        )

    # Also include the as_of_ts + family + desk in the hash so two
    # views of the same manifest at different as_of timestamps differ.
    hash_payload.sort(key=lambda d: d["feature"])
    hash_input = {
        "as_of_ts": as_of_ts.isoformat(),
        "family": family,
        "desk": desk,
        "features": hash_payload,
    }
    view_hash = hashlib.sha256(
        json.dumps(hash_input, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()

    return FeatureView(
        as_of_ts=as_of_ts,
        family=family,
        desk=desk,
        specs=tuple(specs),
        features=features,
        source_eligibility=source_eligibility,
        missingness=missingness,
        stale_flags=stale_flags,
        manifest_ids=manifest_ids,
        forward_fill_used=forward_fill_used,
        view_hash=view_hash,
    )
