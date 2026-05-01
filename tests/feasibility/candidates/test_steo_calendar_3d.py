"""Tests for the STEO calendar audit-only candidate."""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification

import feasibility.candidates.steo_calendar_3d.classical as mod
from feasibility.candidates.steo_calendar_3d.classical import (
    STEO_FEATURE_COLUMNS,
    STEOCalendarLogisticModel,
    build_steo_calendar_features,
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


def _make_steo_events(n: int = 12) -> pd.DataFrame:
    idx = pd.date_range("2020-01-14 17:05", periods=n, freq="MS", tz="UTC")
    release_dates = idx.date
    return pd.DataFrame(
        {
            "issue_label": [f"{ts.year}-{ts.month:02d}" for ts in idx],
            "release_date": [d.isoformat() for d in release_dates],
        },
        index=idx,
    )


def test_classical_model_fits_and_predicts() -> None:
    X, y_01, _, _ = _make_binary_data(n=100)

    model = STEOCalendarLogisticModel()
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
    model = STEOCalendarLogisticModel()
    model.fit(X, y_01)

    result = model.residuals(X, y_sign, ts)

    assert isinstance(result.index, pd.DatetimeIndex)
    assert str(result.index.tzinfo) == "UTC"
    assert set(result.tolist()).issubset({-2, 0, 2})


def test_build_steo_calendar_features_uses_declared_columns() -> None:
    events = _make_steo_events()

    result = build_steo_calendar_features(events)

    assert tuple(result.columns) == STEO_FEATURE_COLUMNS
    assert len(result) == len(events)
    assert np.isfinite(result.to_numpy()).all()
    assert set(result["quarter_start_indicator"].unique()).issubset({0.0, 1.0})
    assert set(result["release_date_override_indicator"].unique()).issubset({0.0, 1.0})


def test_build_steo_calendar_features_rejects_missing_columns() -> None:
    events = _make_steo_events().drop(columns=["release_date"])

    with pytest.raises(ValueError, match="missing required columns"):
        build_steo_calendar_features(events)


def test_build_steo_calendar_features_rejects_non_datetime_index() -> None:
    events = _make_steo_events().reset_index(drop=True)

    with pytest.raises(ValueError, match="indexed by release timestamp"):
        build_steo_calendar_features(events)


def test_module_does_not_export_desk_class() -> None:
    assert getattr(mod, "Desk", None) is None
    assert "feasibility.candidates" in mod.__name__
    assert "desks." not in mod.__name__

    from desks.base import DeskProtocol

    assert not isinstance(STEOCalendarLogisticModel(), DeskProtocol)


def test_module_path_is_under_feasibility_not_desks() -> None:
    loaded = importlib.import_module("feasibility.candidates.steo_calendar_3d.classical")
    assert loaded.__name__.startswith("feasibility.candidates.")
    assert not loaded.__name__.startswith("desks.")
