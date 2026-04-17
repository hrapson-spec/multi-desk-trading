"""Synthetic data generation for gate testing.

Produces deterministic OHLC-like price paths + matched Forecast/Print pairs.
Research-only; no real market data is used (consistent with spec §1.2
synthetic / research-only regime).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta

import numpy as np

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    ClockHorizon,
    DirectionalClaim,
    Forecast,
    Print,
    Provenance,
    UncertaintyInterval,
)


def _provenance(desk_name: str = "test_desk") -> Provenance:
    return Provenance(
        desk_name=desk_name,
        model_name="synthetic",
        model_version="0.0.0",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="0" * 40,
    )


def synthetic_price_path(
    n: int,
    seed: int = 42,
    start_price: float = 80.0,
    drift: float = 0.0,
    vol: float = 0.02,
    ar1_coef: float = 0.0,
) -> np.ndarray:
    """Deterministic GBM (ar1_coef=0) or AR(1) log-return process.

    With ar1_coef != 0, log-returns follow r_t = ar1_coef * r_{t-1} + eps_t
    where eps_t ~ N(drift, vol). Used to inject predictability into
    deepen-phase gate tests; pure random-walk tests keep ar1_coef=0.
    """
    rng = np.random.default_rng(seed)
    shocks = rng.normal(loc=drift, scale=vol, size=n)
    if ar1_coef == 0.0:
        log_returns_series = shocks
    else:
        log_returns_series = np.empty(n)
        log_returns_series[0] = shocks[0]
        for t in range(1, n):
            log_returns_series[t] = ar1_coef * log_returns_series[t - 1] + shocks[t]
    log_returns = np.cumsum(log_returns_series)
    return start_price * np.exp(log_returns)


def make_forecasts_and_prints(
    n: int,
    start_ts_utc: datetime,
    *,
    seed: int = 42,
    desk_name: str = "test_desk",
    forecast_generator: str | Callable[[np.ndarray, int], float] = "noisy_truth",
    horizon: timedelta = timedelta(days=1),
) -> tuple[list[Forecast], list[Print], np.ndarray]:
    """Create n matched (Forecast, Print) pairs over a synthetic price path.

    forecast_generator:
      - "zero": desk emits point_estimate=0 (stub-like)
      - "noisy_truth": desk emits realised + small noise (near-oracle)
      - callable(prices, i) → float: custom
    """
    prices = synthetic_price_path(n + 1, seed=seed)
    forecasts: list[Forecast] = []
    prints: list[Print] = []
    rng = np.random.default_rng(seed + 1)
    for i in range(n):
        emission_ts = start_ts_utc + i * timedelta(days=1)
        realised_ts = emission_ts + horizon
        realised = float(prices[i + 1])

        if forecast_generator == "zero":
            point = 0.0
        elif forecast_generator == "noisy_truth":
            point = realised + float(rng.normal(0.0, 0.5))
        elif callable(forecast_generator):
            point = float(forecast_generator(prices, i))
        else:
            raise ValueError(f"unknown forecast_generator: {forecast_generator!r}")

        forecasts.append(
            Forecast(
                forecast_id=str(uuid.uuid4()),
                emission_ts_utc=emission_ts,
                target_variable=WTI_FRONT_MONTH_CLOSE,
                horizon=ClockHorizon(duration=horizon),
                point_estimate=point,
                uncertainty=UncertaintyInterval(level=0.8, lower=point - 10.0, upper=point + 10.0),
                directional_claim=DirectionalClaim(variable=WTI_FRONT_MONTH_CLOSE, sign="positive"),
                staleness=False,
                confidence=1.0,
                provenance=_provenance(desk_name),
            )
        )
        prints.append(
            Print(
                print_id=str(uuid.uuid4()),
                realised_ts_utc=realised_ts,
                target_variable=WTI_FRONT_MONTH_CLOSE,
                value=realised,
            )
        )
    return forecasts, prints, prices


def persistence_baseline(i: int, prior_prints: Sequence[Print]) -> float:
    """Standard persistence baseline: last observed value, or 0 at t=0.

    NB: use this only when forecast horizon ≈ inter-print interval. For
    multi-day horizons where successive Prints are spaced by the horizon,
    this baseline has an information advantage over any desk that can only
    see price at emission time — use `random_walk_price_baseline` instead.
    """
    if not prior_prints:
        return 0.0
    return float(prior_prints[-1].value)


def random_walk_price_baseline(
    prices: np.ndarray, emission_indices: Sequence[int]
) -> Callable[[int, Sequence[Print]], float]:
    """Factory: baseline_fn that predicts `prices[emission_indices[i] - 1]`.

    This is the spec-level "random walk on wti_front_month_close (one-week
    horizon)" baseline: at each forecast row i, the naive prediction is the
    price observed at emission time (no-change-over-horizon). Both the desk
    and this baseline see the same information set at emission, which is the
    apples-to-apples comparison for Gate 1.
    """

    def _baseline(i: int, _prior_prints: Sequence[Print]) -> float:
        emission_i = emission_indices[i]
        if emission_i < 1:
            return float(prices[0])
        return float(prices[emission_i - 1])

    return _baseline


# placate static analysers for the Callable type hint used in the signature above
from collections.abc import Callable  # noqa: E402

_ = Callable
