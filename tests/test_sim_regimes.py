"""Unit tests for sim.regimes."""

from __future__ import annotations

import numpy as np
import pytest

from sim.regimes import (
    REGIMES,
    RegimeConfig,
    regime_scaling,
    sample_regime_sequence,
)


def test_sample_regime_sequence_is_seed_deterministic():
    cfg = RegimeConfig()
    a = sample_regime_sequence(n_days=200, config=cfg, seed=42)
    b = sample_regime_sequence(n_days=200, config=cfg, seed=42)
    assert a.labels == b.labels
    assert np.array_equal(a.indices, b.indices)


def test_sample_regime_sequence_different_seed_different_path():
    cfg = RegimeConfig()
    a = sample_regime_sequence(n_days=200, config=cfg, seed=1)
    b = sample_regime_sequence(n_days=200, config=cfg, seed=2)
    # Not byte-identical (overwhelmingly likely given 4-state HMC of 200 steps)
    assert a.labels != b.labels


def test_sample_regime_sequence_is_sticky():
    """Sticky HMC: most consecutive-day pairs share a regime."""
    cfg = RegimeConfig()
    seq = sample_regime_sequence(n_days=2000, config=cfg, seed=7)
    same = sum(1 for i in range(1, len(seq)) if seq.labels[i] == seq.labels[i - 1])
    # Diagonals ≥ 0.92 ⇒ expected fraction of same-regime-next-day ≥ 0.92
    assert same / (len(seq) - 1) > 0.90


def test_sample_regime_sequence_explores_all_regimes():
    """Over a 2000-day run we should see every regime at least once."""
    cfg = RegimeConfig()
    seq = sample_regime_sequence(n_days=2000, config=cfg, seed=11)
    observed = set(seq.labels)
    assert observed == set(REGIMES)


def test_sample_regime_sequence_rejects_invalid_config():
    bad_matrix = np.array(
        [
            [0.5, 0.5, 0.0, 0.0],
            [0.0, 0.5, 0.0, 0.5],  # sums OK
            [0.2, 0.2, 0.2, 0.2],  # sums to 0.8 ⇒ invalid
            [0.25, 0.25, 0.25, 0.25],
        ]
    )
    cfg = RegimeConfig(transition_matrix=bad_matrix)
    with pytest.raises(ValueError, match="transition_matrix rows"):
        sample_regime_sequence(n_days=10, config=cfg, seed=0)


def test_regime_scaling_defaults_to_one_for_missing_entries():
    cfg = RegimeConfig()
    assert regime_scaling(cfg, "equilibrium", "supply_vol") == 1.0
    assert regime_scaling(cfg, "supply_dominated", "supply_vol") == 2.5
    assert regime_scaling(cfg, "event_driven", "event_mu0") == 3.0
