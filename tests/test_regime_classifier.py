"""Tests for the Phase A ground-truth pass-through regime classifier."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from desks.regime_classifier import GroundTruthRegimeClassifier
from sim.latent_state import LatentMarket
from sim.observations import ObservationChannels
from sim.regimes import REGIMES


@pytest.fixture
def channels():
    path = LatentMarket(n_days=200, seed=7).generate()
    return ObservationChannels.build(path, mode="clean", seed=0)


def test_regime_label_matches_ground_truth(channels):
    clf = GroundTruthRegimeClassifier()
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    for i in (0, 50, 100, 150, 199):
        label = clf.regime_label_at(channels, i, now)
        expected = channels.latent_path.regimes.regime_at(i)
        assert label.regime_id == expected
        assert label.regime_probabilities[expected] == 1.0
        assert sum(label.regime_probabilities.values()) == 1.0


def test_regime_label_degenerate_probabilities(channels):
    clf = GroundTruthRegimeClassifier()
    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    label = clf.regime_label_at(channels, 100, now)
    non_ground = [r for r in REGIMES if r != label.regime_id]
    for r in non_ground:
        assert label.regime_probabilities[r] == 0.0


def test_regime_classifier_rejects_naive_now_utc(channels):
    clf = GroundTruthRegimeClassifier()
    with pytest.raises(ValueError, match="timezone-aware"):
        clf.regime_label_at(channels, 100, datetime(2026, 4, 16, 10, 0, 0))


def test_regime_classifier_fingerprint_is_deterministic():
    clf = GroundTruthRegimeClassifier()
    assert clf.fingerprint() == clf.fingerprint()
    assert clf.fingerprint().startswith("sha256:")


def test_storage_curve_forecast_from_observation(channels):
    from desks.storage_curve import ClassicalStorageCurveModel, StorageCurveDesk

    # Fit on first 150 days of market_price (train/test split)
    prices = channels.market_price
    model = ClassicalStorageCurveModel(lookback=10, horizon_days=3, alpha=1.0)
    model.fit(prices[:150])
    desk = StorageCurveDesk(model=model)

    now = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
    f = desk.forecast_from_observation(channels, 170, now)
    assert f.staleness is False
    assert f.directional_claim.sign == "positive"

    score = desk.directional_score_from_observation(channels, 170)
    assert score is not None
