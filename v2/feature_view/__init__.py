"""Feature-view boundary between Layer-1 PIT data and desk code.

A desk declares its required inputs as a list of FeatureSpec objects.
`build_feature_view` walks that list, queries the PITReader at a given
`as_of_ts`, applies the declared transforms, and returns a frozen
FeatureView with:

    - `features`: the realised per-feature value (DataFrame / scalar)
    - `source_eligibility`: per-source release-lag + quality snapshot
    - `missingness` + `stale_flags`: per-feature availability markers
    - `view_hash`: deterministic SHA-256 over the canonical input set

The view_hash is the provenance receipt ForecastV2 records. Two
build calls against the same `(as_of_ts, specs, PIT manifest)` must
yield the same hash regardless of ingest wall-clock time.
"""

from v2.feature_view.builder import (
    FeatureViewBuildError,
    build_feature_view,
    identity_transform,
)
from v2.feature_view.spec import FeatureSpec
from v2.feature_view.view import FeatureView

__all__ = [
    "FeatureSpec",
    "FeatureView",
    "FeatureViewBuildError",
    "build_feature_view",
    "identity_transform",
]
