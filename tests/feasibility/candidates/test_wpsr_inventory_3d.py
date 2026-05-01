"""Tests for the WPSR inventory-surprise audit-only candidate."""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification

import feasibility.candidates.wpsr_inventory_3d.classical as mod
from feasibility.candidates.wpsr_inventory_3d.classical import (
    REQUIRED_WPSR_SERIES,
    WPSR_FEATURE_COLUMNS,
    WPSRInventoryLogisticModel,
    build_wpsr_inventory_features,
)


def _make_binary_data(n: int = 100, n_features: int = 5, seed: int = 0) -> tuple:
    X, y_01 = make_classification(
        n_samples=n,
        n_features=n_features,
        n_informative=3,
        n_redundant=1,
        random_state=seed,
    )
    y_sign = np.where(y_01 == 1, 1, -1).astype(int)
    ts = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return X, y_01, y_sign, ts


def _make_wpsr_panel(n: int = 12) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01T15:35:00Z", periods=n, freq="W-WED")
    base = np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "WCESTUS1": 100.0 + base + np.sin(base),
            "WGTSTUS1": 200.0 + 0.5 * base + np.cos(base),
            "WDISTUS1": 150.0 - 0.25 * base + np.sin(base / 2.0),
            "WPULEUS3": 80.0 + 0.1 * base + np.cos(base / 3.0),
            "WCRIMUS2": 50.0 + 0.3 * base + np.sin(base / 4.0),
            "WCREXUS2": 10.0 + 0.2 * base + np.cos(base / 4.0),
        },
        index=idx,
    )


def test_classical_model_fits_and_predicts() -> None:
    X, y_01, _, _ = _make_binary_data(n=100)

    model = WPSRInventoryLogisticModel()
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


def test_residual_values_are_pm_two_or_zero() -> None:
    X, y_01, y_sign, ts = _make_binary_data(n=100)
    model = WPSRInventoryLogisticModel()
    model.fit(X, y_01)

    result = model.residuals(X, y_sign, ts)

    assert isinstance(result.index, pd.DatetimeIndex)
    assert str(result.index.tzinfo) == "UTC"
    assert set(result.tolist()).issubset({-2, 0, 2})


def test_build_wpsr_inventory_features_uses_declared_columns() -> None:
    panel = _make_wpsr_panel()

    result = build_wpsr_inventory_features(panel, window=4, min_periods=2)

    assert tuple(result.columns) == WPSR_FEATURE_COLUMNS
    assert len(result) > 0
    assert np.isfinite(result.to_numpy()).all()
    assert result.index.min() > panel.index.min()


def test_build_wpsr_inventory_features_rejects_missing_series() -> None:
    panel = _make_wpsr_panel().drop(columns=[REQUIRED_WPSR_SERIES[0]])

    with pytest.raises(ValueError, match="missing required series"):
        build_wpsr_inventory_features(panel, window=4, min_periods=2)


def test_module_does_not_export_desk_class() -> None:
    assert getattr(mod, "Desk", None) is None
    assert "feasibility.candidates" in mod.__name__
    assert "desks." not in mod.__name__

    from desks.base import DeskProtocol

    assert not isinstance(WPSRInventoryLogisticModel(), DeskProtocol)


def test_module_path_is_under_feasibility_not_desks() -> None:
    loaded = importlib.import_module("feasibility.candidates.wpsr_inventory_3d.classical")
    assert loaded.__name__.startswith("feasibility.candidates.")
    assert not loaded.__name__.startswith("desks.")
