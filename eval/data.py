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
) -> np.ndarray:
    """Deterministic geometric Brownian motion price path (integer steps)."""
    rng = np.random.default_rng(seed)
    shocks = rng.normal(loc=drift, scale=vol, size=n)
    log_returns = np.cumsum(shocks)
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
    """Standard persistence baseline: last observed value, or 0 at t=0."""
    if not prior_prints:
        return 0.0
    return float(prior_prints[-1].value)


# placate static analysers for the Callable type hint used in the signature above
from collections.abc import Callable  # noqa: E402

_ = Callable
