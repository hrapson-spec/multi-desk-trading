"""Tests for HMMRegimeClassifier (v0.2, plan §A follow-up).

Covers:
  - fit/predict on a synthetic 4-regime path
  - seed determinism (same seed ⇒ byte-identical fit)
  - causal inference (regime_label_at only uses observations up to index i)
  - posterior probabilities sum to 1
  - unfit .regime_label_at raises
  - fit on too-short data raises
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from desks.regime_classifier import HMMRegimeClassifier
from sim.latent_state import LatentMarket, phase_a_config
from sim.observations import ObservationChannels

NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def channels():
    path = LatentMarket(n_days=500, seed=42, config=phase_a_config()).generate()
    return ObservationChannels.build(path, mode="clean", seed=0)


def test_hmm_fits_and_predicts(channels):
    clf = HMMRegimeClassifier(seed=0)
    clf.fit(channels.market_price[:300])
    label = clf.regime_label_at(channels, 350, NOW)
    assert label.regime_id.startswith("hmm_regime_")
    # Probabilities sum to 1 (with small numerical slack)
    assert abs(sum(label.regime_probabilities.values()) - 1.0) < 1e-9
    # Regime_id is the argmax
    assert label.regime_id == max(
        label.regime_probabilities, key=lambda k: label.regime_probabilities[k]
    )


def test_hmm_fingerprint_and_seed_determinism(channels):
    a = HMMRegimeClassifier(seed=7)
    a.fit(channels.market_price[:300])
    b = HMMRegimeClassifier(seed=7)
    b.fit(channels.market_price[:300])
    assert a.fingerprint() == b.fingerprint()

    c = HMMRegimeClassifier(seed=8)
    c.fit(channels.market_price[:300])
    assert a.fingerprint() != c.fingerprint()


def test_hmm_rejects_unfit_predict(channels):
    clf = HMMRegimeClassifier()
    with pytest.raises(RuntimeError, match="not fitted"):
        clf.regime_label_at(channels, 100, NOW)


def test_hmm_rejects_too_short_training(channels):
    clf = HMMRegimeClassifier(n_states=4)
    with pytest.raises(ValueError, match="≥ 40 training"):
        clf.fit(channels.market_price[:10])


def test_hmm_rejects_naive_now_utc(channels):
    clf = HMMRegimeClassifier(seed=0)
    clf.fit(channels.market_price[:300])
    with pytest.raises(ValueError, match="timezone-aware"):
        clf.regime_label_at(channels, 100, datetime(2026, 4, 16, 10, 0, 0))


def test_hmm_causal_inference(channels):
    """The regime label at index i must only depend on observations up to
    index i. This is a critical replay/causality property for the
    Controller — a classifier that looks ahead would leak future info
    into the decision."""
    clf = HMMRegimeClassifier(seed=0)
    clf.fit(channels.market_price[:300])

    # Build a second ObservationChannels where prices after index 350 are
    # arbitrarily perturbed. The classifier label at index 350 must be
    # identical between the two setups.
    perturbed_prices = channels.market_price.copy()
    perturbed_prices[351:] *= 1.5  # big perturbation after the query index

    # Build a fake channels object with the perturbed market price; we
    # construct it by replacing the market_price attribute (frozen
    # dataclass, so use dataclasses.replace).
    import dataclasses

    perturbed_channels = dataclasses.replace(channels, market_price=perturbed_prices)

    label_a = clf.regime_label_at(channels, 350, NOW)
    label_b = clf.regime_label_at(perturbed_channels, 350, NOW)
    assert label_a.regime_id == label_b.regime_id
    for r in label_a.regime_probabilities:
        assert abs(label_a.regime_probabilities[r] - label_b.regime_probabilities[r]) < 1e-12


def test_hmm_all_regime_ids():
    ids = HMMRegimeClassifier.all_regime_ids()
    assert set(ids) == {f"hmm_regime_{k}" for k in range(4)}


def test_hmm_end_to_end_with_controller(channels):
    """End-to-end sanity: fit HMM on training, drive the Controller
    through 50 decisions using HMM-produced regime labels with a
    cold-start weight matrix keyed to HMM regime IDs. Pipeline must
    not error out; decisions emit successfully."""
    from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
    from contracts.v1 import (
        DirectionalClaim,
        EventHorizon,
        Forecast,
        Provenance,
        UncertaintyInterval,
    )
    from controller import Controller, seed_cold_start
    from persistence.db import connect, init_db

    clf = HMMRegimeClassifier(seed=0)
    clf.fit(channels.market_price[:300])

    conn = connect(":memory:")
    init_db(conn)
    boot_ts = NOW
    seed_cold_start(
        conn,
        desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
        regime_ids=HMMRegimeClassifier.all_regime_ids(),
        boot_ts=boot_ts,
        default_cold_start_limit=1e9,
    )
    ctrl = Controller(conn=conn)

    n_decisions = 0
    for i in range(301, 351):
        # build a simple storage_curve forecast from market_price
        forecast_ts = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)
        f = Forecast(
            forecast_id=f"fid-{i:04d}",
            emission_ts_utc=forecast_ts,
            target_variable=WTI_FRONT_MONTH_CLOSE,
            horizon=EventHorizon(event_id="cftc_cot", expected_ts_utc=forecast_ts),
            point_estimate=float(channels.market_price[i]),
            uncertainty=UncertaintyInterval(level=0.8, lower=-1e9, upper=1e9),
            directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="positive"),
            staleness=False,
            confidence=1.0,
            provenance=Provenance(
                desk_name="storage_curve",
                model_name="m",
                model_version="0",
                input_snapshot_hash="0" * 64,
                spec_hash="0" * 64,
                code_commit="0" * 40,
            ),
        )
        label = clf.regime_label_at(channels, i, forecast_ts)
        decision = ctrl.decide(
            now_utc=forecast_ts,
            regime_label=label,
            recent_forecasts={("storage_curve", WTI_FRONT_MONTH_CLOSE): f},
        )
        assert decision.regime_id == label.regime_id
        n_decisions += 1
    conn.close()
    assert n_decisions == 50
