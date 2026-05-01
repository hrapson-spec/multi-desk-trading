"""Tests for the fomc_wti_3d audit-only feasibility candidate.

These tests verify the statistical model interface and confirm the module
does NOT implement DeskProtocol (audit-only positioning constraint).
"""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
from sklearn.datasets import make_classification

import feasibility.candidates.fomc_wti_3d.classical as mod
from feasibility.candidates.fomc_wti_3d.classical import LogisticRegressionFeasibilityModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_binary_data(n: int = 100, n_features: int = 4, seed: int = 0) -> tuple:
    """Synthetic binary classification dataset returning (X, y_01, y_sign, ts)."""
    X, y_01 = make_classification(
        n_samples=n,
        n_features=n_features,
        n_informative=2,
        n_redundant=1,
        random_state=seed,
    )
    y_sign = np.where(y_01 == 1, 1, -1).astype(int)
    ts = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return X, y_01, y_sign, ts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_classical_model_fits_and_predicts() -> None:
    """predict_proba returns probabilities in (0, 1); predict_sign returns ±1."""
    X, y_01, _, _ = _make_binary_data(n=100)

    model = LogisticRegressionFeasibilityModel()
    assert not model.is_fit()

    model.fit(X, y_01)
    assert model.is_fit()

    proba = model.predict_proba(X)
    assert proba.shape == (100,)
    assert float(proba.min()) > 0.0
    assert float(proba.max()) < 1.0

    signs = model.predict_sign(X)
    assert signs.shape == (100,)
    assert set(signs.tolist()).issubset({-1, 1})


def test_residuals_indexed_by_decision_ts() -> None:
    """Residuals series has a UTC DatetimeIndex matching the input decision_ts."""
    X, y_01, y_sign, ts = _make_binary_data(n=100)

    model = LogisticRegressionFeasibilityModel()
    model.fit(X, y_01)

    result = model.residuals(X, y_sign, ts)

    assert isinstance(result.index, pd.DatetimeIndex)
    assert result.index.tzinfo is not None
    assert str(result.index.tzinfo) == "UTC"
    assert len(result) == 100
    pd.testing.assert_index_equal(result.index, ts)


def test_residual_values_are_pm_two_or_zero() -> None:
    """All residual values must be in {-2, 0, +2}."""
    X, y_01, y_sign, ts = _make_binary_data(n=100)

    model = LogisticRegressionFeasibilityModel()
    model.fit(X, y_01)

    result = model.residuals(X, y_sign, ts)

    unique_vals = set(result.tolist())
    assert unique_vals.issubset({-2, 0, 2}), (
        f"Residual values must be in {{-2, 0, +2}}; got {unique_vals}"
    )


def test_module_does_not_export_desk_class() -> None:
    """The module must not export any class that satisfies DeskProtocol.

    The simplest authoritative check: the module path is under
    feasibility.candidates, not desks. Additionally verify no 'Desk'
    attribute exists on the module.
    """
    # No top-level 'Desk' attribute
    assert getattr(mod, "Desk", None) is None

    # Module path must be under feasibility.candidates
    assert "feasibility.candidates" in mod.__name__
    assert "desks." not in mod.__name__

    # Belt-and-suspenders: check that DeskProtocol is importable but that
    # LogisticRegressionFeasibilityModel does not satisfy it at runtime.
    from desks.base import DeskProtocol

    assert not isinstance(LogisticRegressionFeasibilityModel(), DeskProtocol)


def test_module_path_is_under_feasibility_not_desks() -> None:
    """The classical module's __name__ starts with 'feasibility.candidates.'."""
    # Re-import via importlib to confirm the fully-qualified module name.
    loaded = importlib.import_module("feasibility.candidates.fomc_wti_3d.classical")
    assert loaded.__name__.startswith("feasibility.candidates.")
    assert not loaded.__name__.startswith("desks.")
