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

  | Desk              | Primary signals                          |
  |-------------------|------------------------------------------|
  | dealer_inventory  | dealer_flow, vega_exposure               |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .latent_state import EquityVolPath

EquityMode = Literal["clean"]

DESK_NAMES: tuple[str, ...] = ("dealer_inventory", "hedging_demand")


@dataclass(frozen=True)
class EquityDeskObservation:
    """Flat-dict observation for a single equity-VRP desk across n_days."""

    components: dict[str, np.ndarray]
    stale_mask: np.ndarray  # bool, shape (n_days,)
    lag_days: int = 0


@dataclass(frozen=True)
class EquityObservationConfig:
    """Per-desk measurement noise std (clean mode)."""

    dealer_flow_noise_std: float = 0.05
    vega_exposure_noise_std: float = 0.5
    # v1.13 — hedging_demand desk channels.
    hedging_demand_noise_std: float = 0.05
    put_skew_proxy_noise_std: float = 0.1


@dataclass(frozen=True)
class EquityObservationChannels:
    """Observation layer over an EquityVolPath.

    Parallel to `sim.observations.ObservationChannels`. `market_price`
    surfaces vol_level — the classical model predicts next-period vol
    from dealer_flow + vega_exposure, so vol is the "price" series
    baselines compare against.
    """

    latent_path: EquityVolPath
    mode: EquityMode
    market_price: np.ndarray  # shape (n_days,) — vol_level proxy for baselines
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
        by_desk = {
            "dealer_inventory": EquityDeskObservation(
                components={
                    "dealer_flow": flow_obs,
                    "vega_exposure": vega_obs,
                },
                stale_mask=np.zeros(n, dtype=bool),
            ),
            "hedging_demand": EquityDeskObservation(
                components={
                    "hedging_demand_level": hd_obs,
                    "put_skew_proxy": skew_obs,
                },
                stale_mask=np.zeros(n, dtype=bool),
            ),
        }
        # market_price := observed vol level (the thing we're predicting).
        # No noise on the realised price: Prints are ground-truth.
        return cls(
            latent_path=latent,
            mode=mode,
            market_price=latent.vol_level.copy(),
            by_desk=by_desk,
        )
