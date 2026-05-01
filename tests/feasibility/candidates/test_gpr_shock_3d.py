"""Tests for the GPR shock-week audit-only candidate."""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification

import feasibility.candidates.gpr_shock_3d.classical as mod
from feasibility.candidates.gpr_shock_3d.classical import (
    GPR_FEATURE_COLUMNS,
    GPR_VALUE_COLUMNS,
    GPRShockLogisticModel,
    build_gpr_shock_features,
)


def _make_binary_data(n: int = 100, n_features: int = 6, seed: int = 0) -> tuple:
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


def _make_gpr_values(n: int = 20) -> pd.DataFrame:
    idx = pd.date_range("2020-01-03", periods=n, freq="W-FRI", tz="UTC")
    base = np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "GPRD_MA7": 100.0 + base + np.sin(base),
            "GPRD_ACT": 80.0 + 0.5 * base + np.cos(base),
            "GPRD_THREAT": 90.0 - 0.25 * base + np.sin(base / 2.0),
        },
        index=idx,
    )


def test_classical_model_fits_and_predicts() -> None:
    X, y_01, _, _ = _make_binary_data(n=100)

    model = GPRShockLogisticModel()
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
    model = GPRShockLogisticModel()
    model.fit(X, y_01)

    result = model.residuals(X, y_sign, ts)

    assert isinstance(result.index, pd.DatetimeIndex)
    assert str(result.index.tzinfo) == "UTC"
    assert set(result.tolist()).issubset({-2, 0, 2})


def test_build_gpr_shock_features_uses_declared_columns() -> None:
    values = _make_gpr_values()

    result = build_gpr_shock_features(values, window=4, min_periods=2, shock_z=1.0)

    assert tuple(result.columns) == GPR_FEATURE_COLUMNS
    assert len(result) > 0
    assert np.isfinite(result.to_numpy()).all()
    assert set(result["gpr_shock_indicator"].unique()).issubset({0.0, 1.0})


def test_build_gpr_shock_features_rejects_missing_columns() -> None:
    values = _make_gpr_values().drop(columns=[GPR_VALUE_COLUMNS[0]])

    with pytest.raises(ValueError, match="missing required columns"):
        build_gpr_shock_features(values, window=4, min_periods=2)


def test_module_does_not_export_desk_class() -> None:
    assert getattr(mod, "Desk", None) is None
    assert "feasibility.candidates" in mod.__name__
    assert "desks." not in mod.__name__

    from desks.base import DeskProtocol

    assert not isinstance(GPRShockLogisticModel(), DeskProtocol)


def test_module_path_is_under_feasibility_not_desks() -> None:
    loaded = importlib.import_module("feasibility.candidates.gpr_shock_3d.classical")
    assert loaded.__name__.startswith("feasibility.candidates.")
    assert not loaded.__name__.startswith("desks.")
