"""Tests for the OPEC ministerial audit-only candidate."""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification

import feasibility.candidates.opec_ministerial_3d.classical as mod
from feasibility.candidates.opec_ministerial_3d.classical import (
    OPEC_FEATURE_COLUMNS,
    OPECMinisterialLogisticModel,
    build_opec_event_features,
    classify_opec_event,
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


def test_classical_model_fits_and_predicts() -> None:
    X, y_01, _, _ = _make_binary_data(n=100)

    model = OPECMinisterialLogisticModel()
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
    model = OPECMinisterialLogisticModel()
    model.fit(X, y_01)

    result = model.residuals(X, y_sign, ts)

    assert isinstance(result.index, pd.DatetimeIndex)
    assert str(result.index.tzinfo) == "UTC"
    assert set(result.tolist()).issubset({-2, 0, 2})


def test_classify_opec_event_maps_release_content() -> None:
    cut = classify_opec_event("OPEC+_extraordinary_10mb_cut", "ministerial")
    hike = classify_opec_event("OPEC+_production_hike_announcement", "jmmc_with_announcement")
    failed = classify_opec_event("OPEC+_8th_Ministerial_failed", "ministerial")

    assert cut["tightening_indicator"] == 1.0
    assert cut["easing_indicator"] == 0.0
    assert hike["easing_indicator"] == 1.0
    assert hike["jmmc_indicator"] == 1.0
    assert failed["deadlock_indicator"] == 1.0


def test_build_opec_event_features_uses_declared_columns() -> None:
    events = pd.DataFrame(
        {
            "event_label": [
                "OPEC+_voluntary_cut_announcement",
                "OPEC+_production_hike_announcement",
            ],
            "event_type": ["jmmc_with_announcement", "jmmc_with_announcement"],
        },
        index=pd.date_range("2023-01-01", periods=2, freq="D", tz="UTC"),
    )

    result = build_opec_event_features(events)

    assert tuple(result.columns) == OPEC_FEATURE_COLUMNS
    assert result.loc[events.index[0], "tightening_indicator"] == 1.0
    assert result.loc[events.index[1], "easing_indicator"] == 1.0


def test_build_opec_event_features_rejects_missing_columns() -> None:
    events = pd.DataFrame({"event_label": ["OPEC+_cut"]})

    with pytest.raises(ValueError, match="missing required columns"):
        build_opec_event_features(events)


def test_module_does_not_export_desk_class() -> None:
    assert getattr(mod, "Desk", None) is None
    assert "feasibility.candidates" in mod.__name__
    assert "desks." not in mod.__name__

    from desks.base import DeskProtocol

    assert not isinstance(OPECMinisterialLogisticModel(), DeskProtocol)


def test_module_path_is_under_feasibility_not_desks() -> None:
    loaded = importlib.import_module("feasibility.candidates.opec_ministerial_3d.classical")
    assert loaded.__name__.startswith("feasibility.candidates.")
    assert not loaded.__name__.startswith("desks.")
