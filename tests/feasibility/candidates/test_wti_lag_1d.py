"""Tests for the WTI lag 1d audit-only candidate."""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification

import feasibility.candidates.wti_lag_1d.classical as mod
from contracts.target_variables import KNOWN_TARGETS, WTI_FRONT_1D_RETURN_SIGN
from feasibility.candidates.wti_lag_1d.classical import (
    WTILag1DLogisticModel,
    strict_previous_trading_day_log_return,
)


def _make_binary_data(n: int = 100, n_features: int = 1, seed: int = 0) -> tuple:
    X, y_01 = make_classification(
        n_samples=n,
        n_features=n_features,
        n_informative=n_features,
        n_redundant=0,
        n_clusters_per_class=1,
        random_state=seed,
    )
    y_sign = np.where(y_01 == 1, 1, -1).astype(int)
    ts = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return X, y_01, y_sign, ts


def test_strict_previous_trading_day_log_return_avoids_event_day_price() -> None:
    prices = pd.Series(
        [100.0, 110.0, 121.0],
        index=pd.DatetimeIndex(
            ["2026-04-06T00:00:00Z", "2026-04-07T00:00:00Z", "2026-04-08T00:00:00Z"]
        ),
    )

    result = strict_previous_trading_day_log_return(
        pd.Timestamp("2026-04-08T16:05:00Z"),
        prices,
        lag_days=1,
    )

    assert result == pytest.approx(np.log(110.0 / 100.0))


def test_strict_previous_trading_day_log_return_returns_none_without_history() -> None:
    prices = pd.Series(
        [100.0],
        index=pd.DatetimeIndex(["2026-04-06T00:00:00Z"]),
    )

    result = strict_previous_trading_day_log_return(
        pd.Timestamp("2026-04-06T16:05:00Z"),
        prices,
        lag_days=1,
    )

    assert result is None


def test_classical_model_fits_and_predicts() -> None:
    X, y_01, _, _ = _make_binary_data(n=100)

    model = WTILag1DLogisticModel()
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
    model = WTILag1DLogisticModel()
    model.fit(X, y_01)

    result = model.residuals(X, y_sign, ts)

    assert isinstance(result.index, pd.DatetimeIndex)
    assert str(result.index.tzinfo) == "UTC"
    assert set(result.tolist()).issubset({-2, 0, 2})


def test_target_variable_registered() -> None:
    assert WTI_FRONT_1D_RETURN_SIGN in KNOWN_TARGETS


def test_module_does_not_export_desk_class() -> None:
    assert getattr(mod, "Desk", None) is None
    assert "feasibility.candidates" in mod.__name__
    assert "desks." not in mod.__name__

    from desks.base import DeskProtocol

    assert not isinstance(WTILag1DLogisticModel(), DeskProtocol)


def test_module_path_is_under_feasibility_not_desks() -> None:
    loaded = importlib.import_module("feasibility.candidates.wti_lag_1d.classical")
    assert loaded.__name__.startswith("feasibility.candidates.")
    assert not loaded.__name__.startswith("desks.")
