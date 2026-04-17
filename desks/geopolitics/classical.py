"""Classical specialist for the Geopolitics desk (plan §A, spec §5.3).

Consumes the event channel (event_indicator + event_intensity). Features
differ from the supply/demand/macro desks because the signal is a
{0, 1}-ish arrival process on top of a continuous Hawkes intensity —
raw [last, mean, std, trend] is poorly suited. Instead:

  - Rolling event count over `lookback` days
  - Rolling mean intensity
  - Current intensity
  - Days since last event (capped at `lookback`; large values = quiet)

Ridge on this 4-feature vector → log-return → price via market_price.

Phase A debit: real Geopolitics deepen requires LLM event extraction
from news text (OPEC MOMR, GDELT, FT wires). The synthetic regime
supplies a clean Hawkes channel; the LLM ingestion layer is a v0.2
follow-up per plan §A.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.common import fit_ridge

LOOKBACK_DEFAULT = 20  # longer window — events are rare by construction
HORIZON_DEFAULT = 3
ALPHA_DEFAULT = 1.0


@dataclass
class ClassicalGeopoliticsModel:
    """Ridge(event-channel features) → log-return → price."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(self, indicator: np.ndarray, intensity: np.ndarray, i: int) -> np.ndarray | None:
        if i < self.lookback + 1:
            return None
        ind_window = indicator[i - self.lookback : i]
        int_window = intensity[i - self.lookback : i]
        if np.any(~np.isfinite(ind_window)) or np.any(~np.isfinite(int_window)):
            return None
        rolling_count = float(np.nansum(ind_window > 0.5))  # threshold at 0.5 for noisy indicator
        rolling_intensity = float(np.nanmean(int_window))
        current_intensity = float(int_window[-1])
        # Days since last event (capped at lookback)
        fire_idx = np.where(ind_window > 0.5)[0]
        if fire_idx.size:
            days_since = float(self.lookback - fire_idx[-1] - 1)
        else:
            days_since = float(self.lookback)
        return np.array([rolling_count, rolling_intensity, current_intensity, days_since])

    def fit(
        self,
        indicator: np.ndarray,
        intensity: np.ndarray,
        market_price: np.ndarray,
    ) -> None:
        if not (len(indicator) == len(intensity) == len(market_price)):
            raise ValueError("channel array lengths must match")
        X_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(indicator, intensity, i)
            if f is None:
                continue
            log_ret = float(
                np.log(market_price[i + self.horizon_days]) - np.log(market_price[i - 1])
            )
            X_list.append(f)
            y_list.append(log_ret)
        if len(X_list) < 5:
            raise ValueError(f"insufficient training rows: got {len(X_list)}; need ≥5")
        X = np.asarray(X_list, dtype=float)
        y = np.asarray(y_list, dtype=float)
        coef, intercept = fit_ridge(X, y, alpha=self.alpha)
        self.coef_ = coef
        self.intercept_ = intercept
        self.n_train_ = len(X_list)

    def predict(
        self,
        indicator: np.ndarray,
        intensity: np.ndarray,
        market_price: np.ndarray,
        i: int,
    ) -> tuple[float, float] | None:
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        f = self._features(indicator, intensity, i)
        if f is None:
            return None
        log_ret_pred = float(f @ self.coef_ + self.intercept_)
        current_price = float(market_price[i - 1])
        point = current_price * float(np.exp(log_ret_pred))
        directional_score = log_ret_pred
        return point, directional_score

    def fingerprint(self) -> str:
        if self.coef_ is None or self.intercept_ is None:
            return "unfit"
        params = np.concatenate([self.coef_, [self.intercept_]])
        return "sha256:" + hashlib.sha256(params.tobytes()).hexdigest()
