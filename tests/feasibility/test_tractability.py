from __future__ import annotations

import pandas as pd

from feasibility.tractability import (
    Observation,
    build_observations,
    effective_n,
    min_detectable_continuous_effect,
    min_detectable_effect,
)


def _obs(day: str) -> Observation:
    return Observation(
        decision_ts=pd.Timestamp(day, tz="UTC"),
        return_5d=0.01,
        magnitude_5d=0.01,
        mae_conditional_on_direction_5d=0.005,
    )


def test_effective_n_applies_purge_and_embargo_gap():
    observations = [_obs("2026-01-01"), _obs("2026-01-08"), _obs("2026-01-15")]

    assert effective_n(observations, purge_days=5, embargo_days=5) == 2


def test_min_detectable_effect_binary_returns_proportion_lift():
    lift = min_detectable_effect(250, 0.50)

    assert lift is not None
    assert 0.0 < lift < 0.2


def test_min_detectable_continuous_effect_scales_with_std():
    low = min_detectable_continuous_effect(250, 0.02)
    high = min_detectable_continuous_effect(250, 0.04)

    assert low is not None
    assert high is not None
    assert high["raw_effect"] == 2 * low["raw_effect"]
    assert high["standardized_effect"] == low["standardized_effect"]


def test_build_observations_uses_next_available_price_and_forward_mae():
    idx = pd.date_range("2026-01-01", periods=10, freq="D", tz="UTC")
    prices = pd.Series([100, 101, 102, 103, 104, 105, 104, 103, 102, 101], index=idx)

    observations = build_observations(
        [pd.Timestamp("2026-01-01T10:30:00Z")],
        prices,
        horizon_days=5,
    )

    assert len(observations) == 1
    assert observations[0].return_5d > 0
    assert observations[0].mae_conditional_on_direction_5d == 0.0
