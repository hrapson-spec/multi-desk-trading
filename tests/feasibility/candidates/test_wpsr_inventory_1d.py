"""Tests for the WPSR inventory 1d audit-only candidate."""

from __future__ import annotations

import importlib

import numpy as np
import pandas as pd
import pytest
from sklearn.datasets import make_classification

import feasibility.candidates.wpsr_inventory_1d.classical as mod
from feasibility.candidates.wpsr_inventory_1d.classical import (
    REQUIRED_WPSR_SERIES,
    WPSR_FEATURE_COLUMNS,
    WPSRInventory1DLogisticModel,
    _trailing_change_zscore,
    build_wpsr_inventory_features,
)
from feasibility.scripts.audit_wpsr_inventory_1d_phase3 import (
    MIN_TRAIN_EVENTS,
    WalkForwardAudit,
    build_candidate_decision,
    walk_forward_audit,
)


def _make_binary_data(
    n: int = 120,
    n_features: int = len(WPSR_FEATURE_COLUMNS),
    seed: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, pd.DatetimeIndex]:
    X, y_01 = make_classification(
        n_samples=n,
        n_features=n_features,
        n_informative=4,
        n_redundant=1,
        random_state=seed,
    )
    y_sign = np.where(y_01 == 1, 1, -1).astype(int)
    ts = pd.date_range("2020-01-01", periods=n, freq="D", tz="UTC")
    return X, y_01, y_sign, ts


def _make_wpsr_panel(n: int = 14) -> pd.DataFrame:
    idx = pd.date_range("2020-01-01T15:35:00Z", periods=n, freq="W-WED")
    base = np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "WCESTUS1": 100.0 + base + np.sin(base),
            "W_EPC0_SAX_YCUOK_MBBL": 30.0 + 0.2 * base + np.cos(base / 2.0),
            "WGTSTUS1": 200.0 + 0.5 * base + np.cos(base),
            "WDISTUS1": 150.0 - 0.25 * base + np.sin(base / 2.0),
            "WPULEUS3": 80.0 + 0.1 * base + np.cos(base / 3.0),
            "WCRFPUS2": 12.0 + 0.05 * base + np.sin(base / 5.0),
            "WCRIMUS2": 50.0 + 0.3 * base + np.sin(base / 4.0),
            "WCREXUS2": 10.0 + 0.2 * base + np.cos(base / 4.0),
            "WRPUPUS2": 19.0 + 0.15 * base + np.cos(base / 6.0),
        },
        index=idx,
    )


def test_classical_model_fits_and_predicts() -> None:
    X, y_01, _, _ = _make_binary_data()

    model = WPSRInventory1DLogisticModel()
    assert not model.is_fit()

    model.fit(X, y_01)
    assert model.is_fit()

    proba = model.predict_proba(X)
    assert proba.shape == (len(X),)
    assert float(proba.min()) > 0.0
    assert float(proba.max()) < 1.0

    signs = model.predict_sign(X)
    assert signs.shape == (len(X),)
    assert set(signs.tolist()).issubset({-1, 1})


def test_residual_values_are_pm_two_or_zero() -> None:
    X, y_01, y_sign, ts = _make_binary_data()
    model = WPSRInventory1DLogisticModel()
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


def test_trailing_change_zscore_uses_prior_changes_only() -> None:
    series = pd.Series([0.0, 1.0, 3.0, 6.0, 110.0])

    result = _trailing_change_zscore(series, window=3, min_periods=3)

    prior_changes = np.array([1.0, 2.0, 3.0])
    expected = (104.0 - prior_changes.mean()) / prior_changes.std(ddof=0)
    assert result.iloc[-1] == pytest.approx(expected)


def test_build_wpsr_inventory_features_rejects_missing_series() -> None:
    panel = _make_wpsr_panel().drop(columns=[REQUIRED_WPSR_SERIES[1]])

    with pytest.raises(ValueError, match="missing required series"):
        build_wpsr_inventory_features(panel, window=4, min_periods=2)


def test_walk_forward_audit_scores_post_2020_with_pre_2020_training() -> None:
    n = 120
    decision_ts = pd.date_range("2019-01-02", periods=n, freq="W-WED", tz="UTC")
    label_available_ts = decision_ts + pd.Timedelta(days=1)
    x = np.linspace(-2.0, 2.0, n)
    feat_mat = np.column_stack([x, x**2, np.sin(x), np.cos(x), x / 2, -x, x * 0.0])
    label_arr = (x > -0.2).astype(int)

    result = walk_forward_audit(
        feat_mat,
        label_arr,
        decision_ts,
        label_available_ts,
        min_train_events=MIN_TRAIN_EVENTS,
        refit_months=1,
    )

    assert result.scored_events > 0
    assert result.residuals.index.min() >= pd.Timestamp("2020-01-01", tz="UTC")
    assert set(result.scored_frame.columns) == {
        "decision_ts",
        "y_true_sign",
        "y_pred_sign",
        "residual",
    }
    assert result.model_accuracy is not None
    assert result.majority_accuracy_gain_pp is not None


def test_walk_forward_audit_respects_label_availability_gate() -> None:
    n = 80
    decision_ts = pd.date_range("2019-01-02", periods=n, freq="W-WED", tz="UTC")
    feat_mat = np.ones((n, len(WPSR_FEATURE_COLUMNS)), dtype=float)
    label_arr = np.array([0, 1] * (n // 2), dtype=int)
    future_labels = pd.DatetimeIndex(
        [pd.Timestamp("2025-01-01", tz="UTC") for _ in range(n)],
    )

    result = walk_forward_audit(
        feat_mat,
        label_arr,
        decision_ts,
        future_labels,
        min_train_events=MIN_TRAIN_EVENTS,
        refit_months=1,
    )

    assert result.scored_events == 0
    assert result.majority_accuracy_gain_pp is None


def test_candidate_decision_can_pass_n_gate_but_fail_skill_gate() -> None:
    manifest = {
        "decision": {"min_effective_n": 318},
        "targets": {
            "wti_1d_return_sign": {
                "n_after_purge_embargo": 327,
                "n_hac_or_block_adjusted": {
                    "newey_west": {"point_estimate": 318},
                    "block_bootstrap": {"point_estimate": 327},
                },
            },
        },
    }
    metrics = WalkForwardAudit(
        residuals=pd.Series(
            [-2.0, 0.0, 2.0],
            index=pd.date_range("2020-01-01", periods=3, tz="UTC"),
            name="residual",
        ),
        scored_frame=pd.DataFrame(
            {
                "decision_ts": pd.date_range("2020-01-01", periods=3, tz="UTC"),
                "y_true_sign": [-1, 1, -1],
                "y_pred_sign": [1, 1, -1],
                "residual": [-2.0, 0.0, 0.0],
            },
        ),
        model_accuracy=0.474,
        zero_return_baseline_accuracy=0.4801,
        majority_baseline_accuracy=0.5199,
        directional_accuracy_gain_pp=-0.61,
        majority_accuracy_gain_pp=-4.59,
        scored_events=327,
    )

    decision = build_candidate_decision(manifest, metrics)

    assert decision["effective_n_gate_pass"] is True
    assert decision["skill_gate_pass"] is False
    assert decision["final_verdict"] == "NON_ADMISSIBLE"
    assert decision["metrics"]["hac_effective_n"] == 318


def test_module_does_not_export_desk_class() -> None:
    assert getattr(mod, "Desk", None) is None
    assert "feasibility.candidates" in mod.__name__
    assert "desks." not in mod.__name__

    from desks.base import DeskProtocol

    assert not isinstance(WPSRInventory1DLogisticModel(), DeskProtocol)


def test_module_path_is_under_feasibility_not_desks() -> None:
    loaded = importlib.import_module("feasibility.candidates.wpsr_inventory_1d.classical")
    assert loaded.__name__.startswith("feasibility.candidates.")
    assert not loaded.__name__.startswith("desks.")
