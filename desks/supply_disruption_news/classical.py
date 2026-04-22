"""Classical model for the merged supply-disruption-news desk (v1.16).

Ridge-level head on the oil event channel (event_indicator + event_intensity
+ event_intensity_raw). Features:
  - Rolling event count over `lookback` days (indicator > 0.5)
  - Rolling mean intensity
  - Current intensity
  - Days since last event (capped at lookback; large values = quiet)

Ridge on the 4-feature vector → log-return prediction. Horizon pinned at
7 days to match the v1.16 shared oil emission target
`WTI_FRONT_1W_LOG_RETURN`.

Inlined from the legacy `ClassicalGeopoliticsModel` at the post-C12 cleanup
wave (was previously inherited; legacy `desks/geopolitics/` dir is deleted
alongside this inline). Full event-hurdle / Bayesian event-study rebuild
is a §7.3 escalation under debit D1 per the commission at
`docs/pm/supply_disruption_news_engineering_commission.md`.

Phase A debit (inherited from legacy): real disruption-news deepen requires
LLM event extraction from news text (OPEC MOMR, GDELT, FT wires). The
synthetic regime supplies a clean Hawkes channel; the LLM ingestion layer
is a Phase 3 follow-up.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import numpy as np

from desks.common import fit_ridge

LOOKBACK_DEFAULT = 20  # longer window — events are rare by construction
HORIZON_DEFAULT = 7  # v1.16: 1-week emission horizon (was 3 in pre-v1.16)
ALPHA_DEFAULT = 1.0


@dataclass
class ClassicalSupplyDisruptionNewsModel:
    """Ridge(event-channel features) → log-return → price."""

    lookback: int = LOOKBACK_DEFAULT
    horizon_days: int = HORIZON_DEFAULT
    alpha: float = ALPHA_DEFAULT

    coef_: np.ndarray | None = field(default=None, init=False)
    intercept_: float | None = field(default=None, init=False)
    n_train_: int = field(default=0, init=False)

    def _features(
        self,
        indicator: np.ndarray,
        signal: np.ndarray,
        raw_intensity: np.ndarray,
        i: int,
    ) -> np.ndarray | None:
        if i < self.lookback + 1:
            return None
        ind_window = indicator[i - self.lookback : i]
        signal_window = signal[i - self.lookback : i]
        if np.any(~np.isfinite(ind_window)) or np.any(~np.isfinite(signal_window)):
            return None
        rolling_count = float(np.nansum(ind_window > 0.5))
        rolling_signal = float(np.nanmean(signal_window))
        current_signal = float(signal_window[-1])
        fire_idx = np.where(ind_window > 0.5)[0]
        if fire_idx.size:
            days_since = float(self.lookback - fire_idx[-1] - 1)
        else:
            days_since = float(self.lookback)
        return np.array([rolling_count, rolling_signal, current_signal, days_since])

    def fit(
        self,
        indicator: np.ndarray,
        signal: np.ndarray,
        raw_intensity_or_market_price: np.ndarray,
        market_price: np.ndarray | None = None,
    ) -> None:
        if market_price is None:
            raw_intensity = signal
            market_price = raw_intensity_or_market_price
        else:
            raw_intensity = raw_intensity_or_market_price
        if not (len(indicator) == len(signal) == len(raw_intensity) == len(market_price)):
            raise ValueError("channel array lengths must match")
        X_list: list[np.ndarray] = []
        y_list: list[float] = []
        for i in range(1, len(market_price) - self.horizon_days):
            f = self._features(indicator, signal, raw_intensity, i)
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
        signal: np.ndarray,
        raw_intensity_or_market_price: np.ndarray,
        market_price_or_i: np.ndarray | int,
        i: int | None = None,
    ) -> tuple[float, float] | None:
        """Returns (point_price_level, log_return_score) or None.

        The v1.16 SupplyDisruptionNewsDesk unpacks this and emits the
        log-return head as the controller-facing point_estimate (matches
        the WTI_FRONT_1W_LOG_RETURN target).
        """
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model not fitted; call .fit() first")
        if i is None:
            raw_intensity = signal
            market_price = raw_intensity_or_market_price
            i = int(market_price_or_i)
        else:
            raw_intensity = raw_intensity_or_market_price
            market_price = market_price_or_i
        f = self._features(indicator, signal, raw_intensity, i)
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


__all__ = ["ClassicalSupplyDisruptionNewsModel"]
