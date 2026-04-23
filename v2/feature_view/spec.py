"""FeatureSpec: the desk-declared contract for one input feature."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeatureSpec(BaseModel):
    """One input feature a desk reads at decision time.

    A desk publishes its `feature_specs()` as a stable list. Changes
    between preregs constitute a typed contract deviation (see
    docs/v2/promotion_lifecycle.md §8). The list is captured into the
    view_hash via the canonical serialisation in builder.py.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    source: str
    series: str | None = None

    # Transform applied to the raw vintage DataFrame before the value
    # is exposed to the desk. Registered under v2/feature_view/builder.py.
    transform: str = "identity"
    transform_params: dict = Field(default_factory=dict)

    # If `required=True`, absence of an eligible vintage at as_of_ts
    # marks the view as missing-that-feature AND triggers the desk's
    # abstention policy. If `required=False`, the desk is expected to
    # handle the None gracefully.
    required: bool = True

    # Below this quality_multiplier the desk should abstain even if a
    # row is nominally eligible. The builder does NOT enforce this
    # itself; the builder records the multiplier and the desk's
    # abstention logic reads it.
    quality_floor: float = Field(default=0.0, ge=0.0, le=1.0)

    def canonical_key(self) -> tuple:
        """Stable tuple used in the view hash."""
        return (
            self.name,
            self.source,
            self.series or "",
            self.transform,
            tuple(sorted(self.transform_params.items())),
            self.required,
            self.quality_floor,
        )
