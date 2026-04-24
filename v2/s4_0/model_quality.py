"""WTI local/free walk-forward model-quality diagnostics."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

from v2.contracts.decision_unit import FIXED_QUANTILE_LEVELS
from v2.eval.scoring import (
    approx_crps_from_quantiles,
    diebold_mariano_hac,
    mean_pinball_loss,
    pinball_loss,
)


@dataclass(frozen=True)
class WTIModelQualityParams:
    horizon_days: int = 5
    warmup_days: int = 756
    ridge_alpha: float = 10.0
    min_train_samples: int = 252


@dataclass(frozen=True)
class WTIModelQualityReport:
    source_path: str
    rows_total: int
    rows_used: int
    decisions: int
    horizon_days: int
    warmup_days: int
    exogenous_feature_columns: tuple[str, ...]
    min_train_samples_observed: int
    max_train_samples_observed: int
    model_pinball_loss: float
    empirical_pinball_loss: float
    zero_gaussian_pinball_loss: float
    model_crps: float
    empirical_crps: float
    zero_gaussian_crps: float
    pinball_improvement_vs_empirical: float
    pinball_improvement_vs_zero_gaussian: float
    crps_improvement_vs_empirical: float
    crps_improvement_vs_zero_gaussian: float
    directional_accuracy: float
    median_prediction_mean: float
    realised_y_mean: float
    realised_y_std: float
    dm_pinball_vs_empirical: dict[str, float | int]
    dm_pinball_vs_zero_gaussian: dict[str, float | int]
    model_beats_empirical_pinball: bool
    model_beats_zero_gaussian_pinball: bool
    model_beats_empirical_crps: bool
    model_beats_zero_gaussian_crps: bool
    promoted_for_research: bool
    non_claims: tuple[str, ...]
    result_hash: str

    @property
    def ok(self) -> bool:
        return self.decisions > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "rows_total": self.rows_total,
            "rows_used": self.rows_used,
            "decisions": self.decisions,
            "horizon_days": self.horizon_days,
            "warmup_days": self.warmup_days,
            "exogenous_feature_columns": list(self.exogenous_feature_columns),
            "min_train_samples_observed": self.min_train_samples_observed,
            "max_train_samples_observed": self.max_train_samples_observed,
            "model_pinball_loss": self.model_pinball_loss,
            "empirical_pinball_loss": self.empirical_pinball_loss,
            "zero_gaussian_pinball_loss": self.zero_gaussian_pinball_loss,
            "model_crps": self.model_crps,
            "empirical_crps": self.empirical_crps,
            "zero_gaussian_crps": self.zero_gaussian_crps,
            "pinball_improvement_vs_empirical": self.pinball_improvement_vs_empirical,
            "pinball_improvement_vs_zero_gaussian": (
                self.pinball_improvement_vs_zero_gaussian
            ),
            "crps_improvement_vs_empirical": self.crps_improvement_vs_empirical,
            "crps_improvement_vs_zero_gaussian": self.crps_improvement_vs_zero_gaussian,
            "directional_accuracy": self.directional_accuracy,
            "median_prediction_mean": self.median_prediction_mean,
            "realised_y_mean": self.realised_y_mean,
            "realised_y_std": self.realised_y_std,
            "dm_pinball_vs_empirical": self.dm_pinball_vs_empirical,
            "dm_pinball_vs_zero_gaussian": self.dm_pinball_vs_zero_gaussian,
            "model_beats_empirical_pinball": self.model_beats_empirical_pinball,
            "model_beats_zero_gaussian_pinball": self.model_beats_zero_gaussian_pinball,
            "model_beats_empirical_crps": self.model_beats_empirical_crps,
            "model_beats_zero_gaussian_crps": self.model_beats_zero_gaussian_crps,
            "promoted_for_research": self.promoted_for_research,
            "non_claims": list(self.non_claims),
            "ok": self.ok,
            "result_hash": self.result_hash,
        }


def run_wti_model_quality_diagnostic(
    source_path: Path,
    params: WTIModelQualityParams | None = None,
    *,
    exogenous_features: pd.DataFrame | None = None,
) -> WTIModelQualityReport:
    """Run a PIT-safe walk-forward ridge diagnostic on free WTI prices."""
    params = params or WTIModelQualityParams()
    if params.horizon_days <= 0:
        raise ValueError("horizon_days must be > 0")
    if params.warmup_days <= 0:
        raise ValueError("warmup_days must be > 0")
    if params.min_train_samples <= 0:
        raise ValueError("min_train_samples must be > 0")
    if params.ridge_alpha < 0:
        raise ValueError("ridge_alpha must be >= 0")

    prices = load_wti_price_series(source_path)
    frame, exogenous_cols = _feature_frame(
        prices,
        params.horizon_days,
        exogenous_features=exogenous_features,
    )
    if len(frame) < params.warmup_days + params.horizon_days + params.min_train_samples:
        raise ValueError("not enough rows for requested warmup, horizon, and train size")

    feature_cols = [
        "lag1",
        "lag2",
        "mom5",
        "mom20",
        "vol20",
        "vol60",
        "z20",
        *exogenous_cols,
    ]
    levels = np.asarray(FIXED_QUANTILE_LEVELS, dtype=float)
    model_q: list[np.ndarray] = []
    empirical_q: list[np.ndarray] = []
    zero_q: list[np.ndarray] = []
    realised: list[float] = []
    median_predictions: list[float] = []
    train_counts: list[int] = []

    for decision_pos in range(params.warmup_days, len(frame) - params.horizon_days):
        decision_row = frame.iloc[decision_pos]
        if not np.isfinite(decision_row[feature_cols + ["target_5d"]]).all():
            continue

        train_cutoff = decision_pos - params.horizon_days + 1
        train = frame.iloc[:train_cutoff].dropna(subset=[*feature_cols, "target_5d"])
        if len(train) < params.min_train_samples:
            continue

        x_train = train[feature_cols].to_numpy(dtype=float)
        y_train = train["target_5d"].to_numpy(dtype=float)
        x = decision_row[feature_cols].to_numpy(dtype=float)
        prediction, residual_sigma = _ridge_predict(
            x_train, y_train, x, alpha=params.ridge_alpha
        )
        model_row = prediction + residual_sigma * norm.ppf(levels)
        empirical_row = np.quantile(y_train, levels)
        zero_sigma = max(float(np.std(y_train, ddof=1)), 1e-12)
        zero_row = zero_sigma * norm.ppf(levels)

        model_q.append(model_row)
        empirical_q.append(empirical_row)
        zero_q.append(zero_row)
        realised.append(float(decision_row["target_5d"]))
        median_predictions.append(float(prediction))
        train_counts.append(len(train))

    if not realised:
        raise ValueError("no walk-forward decisions generated")

    y = np.asarray(realised, dtype=float)
    model = np.asarray(model_q, dtype=float)
    empirical = np.asarray(empirical_q, dtype=float)
    zero = np.asarray(zero_q, dtype=float)
    medians = np.asarray(median_predictions, dtype=float)

    model_pinball = mean_pinball_loss(y, model, levels)
    empirical_pinball = mean_pinball_loss(y, empirical, levels)
    zero_pinball = mean_pinball_loss(y, zero, levels)
    model_crps = approx_crps_from_quantiles(y, model, levels)
    empirical_crps = approx_crps_from_quantiles(y, empirical, levels)
    zero_crps = approx_crps_from_quantiles(y, zero, levels)
    model_loss_series = pinball_loss(y, model, levels).mean(axis=1)
    empirical_loss_series = pinball_loss(y, empirical, levels).mean(axis=1)
    zero_loss_series = pinball_loss(y, zero, levels).mean(axis=1)
    dm_empirical = diebold_mariano_hac(model_loss_series, empirical_loss_series)
    dm_zero = diebold_mariano_hac(model_loss_series, zero_loss_series)
    directional = float((np.sign(medians) == np.sign(y)).mean())
    promoted = (
        model_pinball < empirical_pinball
        and model_pinball < zero_pinball
        and model_crps < empirical_crps
        and model_crps < zero_crps
        and directional > 0.5
    )
    payload = {
        "source_path": str(source_path),
        "rows_used": int(len(frame)),
        "decisions": int(y.size),
        "model_pinball_loss": model_pinball,
        "empirical_pinball_loss": empirical_pinball,
        "zero_gaussian_pinball_loss": zero_pinball,
        "model_crps": model_crps,
        "empirical_crps": empirical_crps,
        "zero_gaussian_crps": zero_crps,
        "exogenous_feature_columns": exogenous_cols,
        "directional_accuracy": directional,
        "promoted_for_research": promoted,
    }
    return WTIModelQualityReport(
        source_path=str(source_path),
        rows_total=int(prices.size),
        rows_used=int(len(frame)),
        decisions=int(y.size),
        horizon_days=params.horizon_days,
        warmup_days=params.warmup_days,
        exogenous_feature_columns=tuple(exogenous_cols),
        min_train_samples_observed=int(min(train_counts)),
        max_train_samples_observed=int(max(train_counts)),
        model_pinball_loss=model_pinball,
        empirical_pinball_loss=empirical_pinball,
        zero_gaussian_pinball_loss=zero_pinball,
        model_crps=model_crps,
        empirical_crps=empirical_crps,
        zero_gaussian_crps=zero_crps,
        pinball_improvement_vs_empirical=_relative_improvement(
            empirical_pinball, model_pinball
        ),
        pinball_improvement_vs_zero_gaussian=_relative_improvement(
            zero_pinball, model_pinball
        ),
        crps_improvement_vs_empirical=_relative_improvement(empirical_crps, model_crps),
        crps_improvement_vs_zero_gaussian=_relative_improvement(zero_crps, model_crps),
        directional_accuracy=directional,
        median_prediction_mean=float(medians.mean()),
        realised_y_mean=float(y.mean()),
        realised_y_std=float(y.std(ddof=1)),
        dm_pinball_vs_empirical=_dm_payload(dm_empirical),
        dm_pinball_vs_zero_gaussian=_dm_payload(dm_zero),
        model_beats_empirical_pinball=model_pinball < empirical_pinball,
        model_beats_zero_gaussian_pinball=model_pinball < zero_pinball,
        model_beats_empirical_crps=model_crps < empirical_crps,
        model_beats_zero_gaussian_crps=model_crps < zero_crps,
        promoted_for_research=promoted,
        non_claims=(
            "not a live trading result",
            "not an investment-performance result",
            "not a production-readiness result",
            "uses local/free WTI spot proxy data, not licensed CL order-book data",
        ),
        result_hash=_sha256_json(payload),
    )


def load_wti_price_series(source_path: Path) -> pd.Series:
    """Load either FRED DCOILWTICO or S4 replay-style WTI price CSV."""
    source_path = Path(source_path)
    with source_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError("CSV has no header")
        fields = set(reader.fieldnames)
    if {"observation_date", "DCOILWTICO"} <= fields:
        frame = pd.read_csv(source_path)
        ts = pd.to_datetime(frame["observation_date"], utc=True)
        price = pd.to_numeric(frame["DCOILWTICO"], errors="coerce")
    elif {"ts_event", "price"} <= fields:
        frame = pd.read_csv(source_path)
        ts = pd.to_datetime(frame["ts_event"], utc=True)
        price = pd.to_numeric(frame["price"], errors="coerce")
    else:
        raise ValueError("CSV must contain FRED or S4 replay price columns")
    series = pd.Series(price.to_numpy(dtype=float), index=pd.DatetimeIndex(ts))
    series = series.dropna()
    series = series[series > 0].sort_index()
    series = series[~series.index.duplicated(keep="last")]
    if series.size < 10:
        raise ValueError("price series too short")
    return series


def _feature_frame(
    price: pd.Series,
    horizon_days: int,
    *,
    exogenous_features: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    log_price = np.log(price)
    ret1 = log_price.diff()
    frame = pd.DataFrame(index=price.index)
    frame["price"] = price
    frame["lag1"] = ret1
    frame["lag2"] = ret1.shift(1)
    frame["mom5"] = log_price.diff(5)
    frame["mom20"] = log_price.diff(20)
    frame["vol20"] = ret1.rolling(20).std()
    frame["vol60"] = ret1.rolling(60).std()
    frame["z20"] = (price / price.rolling(20).mean()) - 1.0
    frame["target_5d"] = log_price.shift(-horizon_days) - log_price
    if exogenous_features is None:
        return frame, []
    return _merge_exogenous_features(frame, exogenous_features)


def _merge_exogenous_features(
    frame: pd.DataFrame,
    exogenous_features: pd.DataFrame,
) -> tuple[pd.DataFrame, list[str]]:
    if not isinstance(exogenous_features.index, pd.DatetimeIndex):
        raise ValueError("exogenous_features must use a DatetimeIndex")
    exog = exogenous_features.copy()
    exog.index = pd.DatetimeIndex(pd.to_datetime(exog.index, utc=True))
    exog = exog.sort_index()
    exog = exog[~exog.index.duplicated(keep="last")]
    numeric = exog.apply(pd.to_numeric, errors="coerce")
    numeric = numeric.dropna(axis=1, how="all")
    if numeric.empty:
        raise ValueError("exogenous_features must contain numeric columns")
    renamed = {
        column: f"exog_{column}"
        for column in numeric.columns
    }
    numeric = numeric.rename(columns=renamed)
    left = frame.reset_index(names="decision_ts").sort_values("decision_ts")
    right = numeric.reset_index(names="decision_ts").sort_values("decision_ts")
    merged = pd.merge_asof(
        left,
        right,
        on="decision_ts",
        direction="backward",
        allow_exact_matches=True,
    )
    merged = merged.set_index("decision_ts")
    return merged, list(renamed.values())


def _ridge_predict(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x: np.ndarray,
    *,
    alpha: float,
) -> tuple[float, float]:
    mean = x_train.mean(axis=0)
    std = x_train.std(axis=0)
    std = np.where(std <= 1e-12, 1.0, std)
    x_train_std = (x_train - mean) / std
    x_std = (x - mean) / std
    design = np.column_stack([np.ones(x_train_std.shape[0]), x_train_std])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    beta = np.linalg.solve(design.T @ design + penalty, design.T @ y_train)
    fitted = design @ beta
    residuals = y_train - fitted
    sigma = max(float(np.std(residuals, ddof=1)), 1e-12)
    prediction = float(np.r_[1.0, x_std] @ beta)
    return prediction, sigma


def _relative_improvement(baseline: float, model: float) -> float:
    denominator = max(abs(baseline), 1e-12)
    return float((baseline - model) / denominator)


def _dm_payload(result) -> dict[str, float | int]:
    return {
        "mean_diff": float(result.mean_diff),
        "variance_hac": float(result.variance_hac),
        "dm_stat": float(result.dm_stat),
        "lag": int(result.lag),
        "n": int(result.n),
    }


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()
