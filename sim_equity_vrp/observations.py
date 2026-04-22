"""Equity-vol observation channels (Phase 2 MVP).

Parallel to `sim/observations.py`. Minimal fidelity — only the clean
mode is implemented, which is all the Phase 2 MVP needs to prove
portability. Leakage + realistic modes are a follow-on (mirrors
Phase B/C in the oil sim).

Output shape is identical across modes: `channels.by_desk[desk_name]`
is an `EquityDeskObservation` with the arrays the desk's classical
specialist expects. The sole mode in the MVP is `clean`, where each
desk sees its own latent channel plus iid Gaussian noise.

Desk-to-channel map (equity-VRP):

  | Desk                          | Primary signals                              |
  |-------------------------------|----------------------------------------------|
  | dealer_inventory (legacy)     | dealer_flow, vega_exposure                   |
  | hedging_demand (legacy)       | hedging_demand_level, put_skew_proxy         |
  | surface_positioning_feedback  | all four components (v1.16 merged view)      |
  | earnings_calendar             | earnings_event_indicator, earnings_cluster_size (v1.16 X1) |

v1.16 (C9): `by_desk["surface_positioning_feedback"]` is added alongside the
legacy `dealer_inventory` and `hedging_demand` keys. Component arrays are
shared views of the same underlying numpy buffers — no duplication in
memory, and the legacy keys continue to expose their original subset until
C12 removes them together with the legacy desk directories.

v1.16 (X1): `by_desk["earnings_calendar"]` exposes the earnings-event
channel generated in `latent_state.py` with a forward-correlation to
`vol_shocks_unscaled` at a 2-step lead. Observation noise is not added —
the indicator is binary and the cluster size is a count.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .latent_state import EquityVolPath

EquityMode = Literal["clean"]

DESK_NAMES: tuple[str, ...] = (
    "dealer_inventory",
    "hedging_demand",
    "surface_positioning_feedback",
    "earnings_calendar",
)


@dataclass(frozen=True)
class EquityDeskObservation:
    """Flat-dict observation for a single equity-VRP desk across n_days."""

    components: dict[str, np.ndarray]
    stale_mask: np.ndarray  # bool, shape (n_days,)
    lag_days: int = 0


@dataclass(frozen=True)
class EquityObservationConfig:
    """Per-desk measurement noise std (clean mode) + v1.16 fair_vol_baseline knobs."""

    dealer_flow_noise_std: float = 0.05
    vega_exposure_noise_std: float = 0.5
    # v1.13 — hedging_demand desk channels.
    hedging_demand_noise_std: float = 0.05
    put_skew_proxy_noise_std: float = 0.1
    # v1.16 (C11) — decision-time forward-vol baseline used by
    # surface_positioning_feedback to compute next_session_rv_surprise
    # as an INTERNAL auxiliary label (never emitted to Controller).
    #   fair_vol_baseline[t] = vol_level[t-lag-lookback : t-lag].mean()
    # This guarantees a strict function of vol_level[<t] — decision-time safe.
    # For t < lag + lookback the baseline falls back to the OU mean
    # (vol_mean_baseline) from EquityVolMarketConfig.
    fair_vol_baseline_lookback: int = 20
    fair_vol_baseline_lag: int = 1


@dataclass(frozen=True)
class EquityObservationChannels:
    """Observation layer over an EquityVolPath.

    Parallel to `sim.observations.ObservationChannels`. `market_price`
    surfaces vol_level — the classical model predicts next-period vol
    from dealer_flow + vega_exposure, so vol is the "price" series
    baselines compare against.

    v1.16 (C11) — `fair_vol_baseline` is a decision-time-safe forward-vol
    reference (trailing-k-day mean of vol_level with explicit lag).
    Used by `surface_positioning_feedback` to compute the internal
    auxiliary label `next_session_rv_surprise` = realised - fair_vol_baseline.
    NEVER emitted to the Controller — internal training signal only.
    """

    latent_path: EquityVolPath
    mode: EquityMode
    market_price: np.ndarray  # shape (n_days,) — vol_level proxy for baselines
    fair_vol_baseline: np.ndarray = field(
        default_factory=lambda: np.zeros(0, dtype=np.float64)
    )
    by_desk: dict[str, EquityDeskObservation] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        latent: EquityVolPath,
        *,
        mode: EquityMode = "clean",
        seed: int = 0,
        config: EquityObservationConfig | None = None,
    ) -> EquityObservationChannels:
        if mode != "clean":
            raise NotImplementedError(f"mode={mode!r} not implemented for Phase 2 MVP (clean only)")
        cfg = config if config is not None else EquityObservationConfig()
        rng = np.random.default_rng(seed)

        n = latent.n_days
        # dealer_inventory sees dealer_flow + vega_exposure with noise.
        # These draws MUST come first — v1.13 hedging_demand noise uses an
        # isolated RNG stream so this ordering stays bit-identical to v1.12.
        flow_obs = latent.dealer_flow + rng.standard_normal(n) * cfg.dealer_flow_noise_std
        vega_obs = latent.vega_exposure + rng.standard_normal(n) * cfg.vega_exposure_noise_std
        # v1.13: hedging_demand channels on a SEPARATE RNG (seed+3) so the
        # main `rng` stream advances identically to v1.12 → dealer_inventory
        # golden fixtures hold.
        hd_rng = np.random.default_rng((seed + 3) & 0xFFFFFFFF)
        hd_obs = latent.hedging_demand + hd_rng.standard_normal(n) * cfg.hedging_demand_noise_std
        skew_obs = latent.put_skew_proxy + hd_rng.standard_normal(n) * cfg.put_skew_proxy_noise_std
        stale_mask_zero = np.zeros(n, dtype=bool)
        by_desk = {
            "dealer_inventory": EquityDeskObservation(
                components={
                    "dealer_flow": flow_obs,
                    "vega_exposure": vega_obs,
                },
                stale_mask=stale_mask_zero,
            ),
            "hedging_demand": EquityDeskObservation(
                components={
                    "hedging_demand_level": hd_obs,
                    "put_skew_proxy": skew_obs,
                },
                stale_mask=stale_mask_zero,
            ),
            # v1.16 C9: merged-view desk. Exposes all four components under
            # one key so `SurfacePositioningFeedbackDesk` does not need to
            # read two different keys. Arrays are shared views (not copies)
            # of the same numpy buffers used by the legacy keys — zero
            # duplication, and D12 golden fixtures hold because the legacy
            # keys' component arrays are byte-identical to before.
            "surface_positioning_feedback": EquityDeskObservation(
                components={
                    "dealer_flow": flow_obs,
                    "vega_exposure": vega_obs,
                    "hedging_demand_level": hd_obs,
                    "put_skew_proxy": skew_obs,
                },
                stale_mask=stale_mask_zero,
            ),
            # v1.16 X1: earnings-calendar desk. Exposes the two arrays
            # generated in latent_state.py (earnings_event_indicator and
            # earnings_cluster_size). No observation noise — indicators
            # are binary, cluster size is a count.
            "earnings_calendar": EquityDeskObservation(
                components={
                    "earnings_event_indicator": latent.earnings_event_indicator,
                    "earnings_cluster_size": latent.earnings_cluster_size,
                },
                stale_mask=stale_mask_zero,
            ),
        }
        # market_price := observed vol level (the thing we're predicting).
        # No noise on the realised price: Prints are ground-truth.
        market_price = latent.vol_level.copy()
        # v1.16 (C11) fair_vol_baseline: trailing-k-day mean of vol_level
        # with explicit `fair_vol_baseline_lag`-day lag. Decision-time safe
        # by construction — fair_vol_baseline[t] is a strict function of
        # vol_level[< t] (lag >= 1). Warm-up indices (t < lag + lookback)
        # default to the OU baseline mean from EquityVolMarketConfig.
        lookback = cfg.fair_vol_baseline_lookback
        lag = cfg.fair_vol_baseline_lag
        fair_vol_baseline = np.full(n, latent.vol_level[0], dtype=np.float64)
        warmup = lag + lookback
        for t in range(warmup, n):
            fair_vol_baseline[t] = float(market_price[t - lag - lookback : t - lag].mean())
        return cls(
            latent_path=latent,
            mode=mode,
            market_price=market_price,
            fair_vol_baseline=fair_vol_baseline,
            by_desk=by_desk,
        )
