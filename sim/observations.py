"""Per-desk observation channels over a LatentPath (plan §A).

Three modes, selectable at construction time:

  - **clean** (Phase A): each desk sees its own latent channel with iid
    Gaussian noise. Diagnostic mode that isolates desk + Controller +
    attribution testing from the confounding effects of real-world
    information leakage.

  - **leakage** (Phase B): each desk's observation is a diagonal-dominant
    mixture of every latent channel. Mixing matrix is fixed, logged, and
    replay-deterministic. Tests graceful degradation under controlled
    confounding.

  - **realistic** (Phase C): mixing matrix becomes regime-dependent;
    shared "macro chatter" common component added during event regimes;
    per-day staleness flags simulate ingest failures; publication lags
    shift desk observations off the latent clock. Tests the architecture's
    honest failure boundary under the kinds of contamination a real
    multi-desk shop faces.

Output shape is identical across modes: `channels[desk_name]` is a
`DeskObservation` with the arrays the desk's classical specialist expects.
Downstream desk code is mode-agnostic.

**Desk-to-channel map (all modes share this mapping; only the noise /
leakage / contamination change):**

  | Desk            | Primary signals                                        |
  |-----------------|--------------------------------------------------------|
  | storage_curve   | price, balance = (supply − demand)                     |
  | supply          | supply state                                           |
  | demand          | demand state                                           |
  | geopolitics     | event_indicator, event_intensity                       |
  | macro           | xi (long-run log-equilibrium)                          |
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np

from .latent_state import LatentPath

Mode = Literal["clean", "leakage", "realistic"]

DESK_NAMES: tuple[str, ...] = (
    "storage_curve",
    "supply",
    "demand",
    "geopolitics",
    "macro",
)


@dataclass(frozen=True)
class DeskObservation:
    """Flat-dict observation for a single desk across n_days.

    `components` maps signal_name → ndarray[n_days]. `stale_mask` flags
    days on which the desk's ingest failed (Phase C only; all False in
    Phase A/B). `lag_days` is the publication lag applied to the signals
    (0 for Phase A/B; per-desk positive int in Phase C).
    """

    components: dict[str, np.ndarray]
    stale_mask: np.ndarray  # bool, shape (n_days,)
    lag_days: int = 0


@dataclass(frozen=True)
class ObservationConfig:
    """Noise / leakage / contamination knobs, all replay-deterministic."""

    # Per-desk measurement noise std (clean mode; also baseline for other
    # modes). Non-price channels carry AR(1) return streams whose daily
    # stationary std is ~0.01; noise is an order of magnitude smaller so
    # the signal remains identifiable.
    noise_std: dict[str, float] = field(
        default_factory=lambda: {
            "storage_curve": 0.01,  # 1% of price
            "supply": 0.001,
            "demand": 0.001,
            "geopolitics": 0.002,
            "macro": 0.001,
        }
    )

    # Leakage mode: off-diagonal weight on the 5×5 mixing matrix. Diagonals
    # are (1 − leakage_strength) and off-diagonals share the remainder.
    leakage_strength: float = 0.1

    # Realistic mode adds:
    # Per-desk staleness probability per day
    staleness_prob: dict[str, float] = field(
        default_factory=lambda: {
            "storage_curve": 0.01,
            "supply": 0.03,  # weekly-ish feed; more gaps
            "demand": 0.03,
            "geopolitics": 0.05,  # noisy scraping
            "macro": 0.02,
        }
    )
    # Per-desk publication lag (days)
    publication_lag: dict[str, int] = field(
        default_factory=lambda: {
            "storage_curve": 0,
            "supply": 1,  # prior-day release
            "demand": 1,
            "geopolitics": 0,  # news hits same-day
            "macro": 5,  # weekly/monthly releases
        }
    )
    # Shared macro chatter amplitude (added during event-driven regime)
    chatter_amplitude: float = 0.10


MARKET_PRICE_NOISE_STD = 0.005  # every desk sees market price with small noise


@dataclass(frozen=True)
class ObservationChannels:
    """Dispatcher returning `channels[desk_name] → DeskObservation`.

    Construct with a LatentPath + mode + config; call `.by_desk[name]`.

    `market_price` is the price stream every desk has access to (WTI
    ticker is a shared observable). Per-desk classical specialists use
    it as the reference for their log-return conversion to a Forecast
    `point_estimate`. Noise on market_price is small (realistic for
    exchange-traded products) and shared across desks.
    """

    by_desk: dict[str, DeskObservation]
    market_price: np.ndarray
    mode: Mode
    config: ObservationConfig
    seed: int
    latent_path: LatentPath

    @classmethod
    def build(
        cls,
        latent: LatentPath,
        *,
        mode: Mode,
        seed: int,
        config: ObservationConfig | None = None,
    ) -> ObservationChannels:
        if mode not in ("clean", "leakage", "realistic"):
            raise ValueError(f"mode must be clean|leakage|realistic; got {mode!r}")
        cfg = config if config is not None else ObservationConfig()

        if mode == "clean":
            by_desk = _build_clean(latent, cfg, seed)
        elif mode == "leakage":
            by_desk = _build_leakage(latent, cfg, seed)
        else:
            by_desk = _build_realistic(latent, cfg, seed)

        # Shared market-price observable across all desks.
        n = latent.n_days
        rng_mp = _rng_for(seed, 999)
        market_price = latent.price * (1.0 + MARKET_PRICE_NOISE_STD * rng_mp.standard_normal(n))

        return cls(
            by_desk=by_desk,
            market_price=market_price,
            mode=mode,
            config=cfg,
            seed=seed,
            latent_path=latent,
        )


# ---------------------------------------------------------------------------
# Mode builders
# ---------------------------------------------------------------------------


def _rng_for(seed: int, stream_id: int) -> np.random.Generator:
    """Deterministic per-stream RNG."""
    return np.random.default_rng(np.random.SeedSequence([seed, stream_id]))


def _build_clean(
    latent: LatentPath, cfg: ObservationConfig, seed: int
) -> dict[str, DeskObservation]:
    """Clean 1:1 observations (Phase A). Each desk sees its own latent
    factor + its own AR(1) return driver layered on top. The AR(1)
    driver is what makes each desk's channel predictively informative
    about the next horizon's log-return; the OU fundamental layer stays
    as realism."""
    n = latent.n_days
    rng_sc, rng_s, rng_d, rng_g, rng_m = (_rng_for(seed, k) for k in range(5))

    price = latent.price
    balance = latent.balance
    supply = latent.supply
    demand = latent.demand
    events = latent.event_indicator.astype(float)
    intensity = latent.event_intensity
    xi = latent.xi

    sc_noise_price = cfg.noise_std["storage_curve"] * price * rng_sc.standard_normal(n)
    sc_noise_balance = cfg.noise_std["storage_curve"] * rng_sc.standard_normal(n)
    s_noise = cfg.noise_std["supply"] * rng_s.standard_normal(n)
    d_noise = cfg.noise_std["demand"] * rng_d.standard_normal(n)
    g_noise_ind = cfg.noise_std["geopolitics"] * rng_g.standard_normal(n)
    g_noise_int = cfg.noise_std["geopolitics"] * rng_g.standard_normal(n)
    m_noise = cfg.noise_std["macro"] * rng_m.standard_normal(n)

    # Per-desk AR(1) return stream exposed directly as a "signal" channel.
    # This is what gives each desk predictively-useful information about
    # future log-return; the OU fundamentals stay as architectural
    # flavouring. Each desk's classical specialist treats its channel
    # value as a signal in return space.
    ar1 = latent.desk_ar1

    stale_false = np.zeros(n, dtype=bool)
    return {
        # storage_curve sees price directly; its AR(1) driver is already
        # baked into the log-price via the latent state's cumulative sum.
        "storage_curve": DeskObservation(
            components={
                "price": price + sc_noise_price,
                "balance": balance + sc_noise_balance,
            },
            stale_mask=stale_false,
        ),
        # Non-storage desks see a "signal" channel = AR(1) return stream.
        # The OU fundamental (supply / demand / xi / event_intensity) is
        # still exposed as an auxiliary component.
        "supply": DeskObservation(
            components={
                "supply": ar1["supply"] + s_noise,
                "supply_level": supply,  # aux: OU level, not used by the Phase A ridge
            },
            stale_mask=stale_false,
        ),
        "demand": DeskObservation(
            components={
                "demand": ar1["demand"] + d_noise,
                "demand_level": demand,
            },
            stale_mask=stale_false,
        ),
        "geopolitics": DeskObservation(
            components={
                "event_indicator": events + g_noise_ind,
                "event_intensity": ar1["geopolitics"] + g_noise_int,
                "event_intensity_raw": intensity,  # aux
            },
            stale_mask=stale_false,
        ),
        "macro": DeskObservation(
            components={
                "xi": ar1["macro"] + m_noise,
                "xi_level": xi,  # aux
            },
            stale_mask=stale_false,
        ),
    }


def _latent_vector(latent: LatentPath) -> np.ndarray:
    """Stack the five primary latent signals into an (n_days, 5) matrix
    indexed in DESK_NAMES order.

    For multi-component desks we use a representative scalar per desk so
    the mixing matrix can be a square 5×5. The representative:
      storage_curve → log_price (correlates most directly)
      supply        → supply
      demand        → demand
      geopolitics   → event_intensity (continuous)
      macro         → xi
    """
    return np.column_stack(
        [latent.log_price, latent.supply, latent.demand, latent.event_intensity, latent.xi]
    )


def _standardize(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (Z, mu, sigma) where Z = (matrix - mu) / sigma per column.
    sigma floor at 1e-9 so degenerate columns don't divide by zero."""
    mu = matrix.mean(axis=0)
    sigma = matrix.std(axis=0)
    sigma = np.where(sigma < 1e-9, 1.0, sigma)
    return (matrix - mu) / sigma, mu, sigma


def _mixing_matrix(leakage: float) -> np.ndarray:
    """5×5 diagonal-dominant mixing matrix. Diagonal = 1 − leakage;
    off-diagonals = leakage / 4 (uniform spread). Rows sum to 1."""
    n = 5
    m = np.full((n, n), leakage / (n - 1))
    np.fill_diagonal(m, 1.0 - leakage)
    return m


def _apply_lag(arr: np.ndarray, lag: int) -> np.ndarray:
    """Shift signal forward by `lag` days (what the desk sees today = value
    `lag` days ago). Leading `lag` entries are filled with the first
    observable value to avoid introducing NaN at the boundary."""
    if lag <= 0:
        return arr
    shifted = np.empty_like(arr)
    shifted[:lag] = arr[0]
    shifted[lag:] = arr[:-lag]
    return shifted


def _build_leakage(
    latent: LatentPath, cfg: ObservationConfig, seed: int
) -> dict[str, DeskObservation]:
    """Phase B (plan §A): diagonal-dominant mixing on the per-desk AR(1)
    return streams. Each non-storage desk's primary channel is
    (1 − leakage_strength) × own AR(1) + (leakage_strength / 4) × sum
    of other desks' AR(1) + noise. Storage_curve still sees price
    directly (price already embeds every desk's AR(1) via the log-price
    cumulative sum).
    """
    n = latent.n_days
    rngs = [_rng_for(seed, 100 + k) for k in range(5)]

    m = _mixing_matrix(cfg.leakage_strength)
    ar1 = latent.desk_ar1
    ar1_matrix = np.column_stack([ar1[d] for d in DESK_NAMES])
    mixed = ar1_matrix @ m.T  # (n, 5) — each column is the mixed signal for that desk

    stale_false = np.zeros(n, dtype=bool)
    price = latent.price
    balance = latent.balance
    sc_noise_p = cfg.noise_std["storage_curve"] * price * rngs[0].standard_normal(n)
    sc_noise_b = cfg.noise_std["storage_curve"] * rngs[0].standard_normal(n)

    supply_obs = mixed[:, 1] + cfg.noise_std["supply"] * rngs[1].standard_normal(n)
    demand_obs = mixed[:, 2] + cfg.noise_std["demand"] * rngs[2].standard_normal(n)
    intensity_obs = mixed[:, 3] + cfg.noise_std["geopolitics"] * rngs[3].standard_normal(n)
    indicator_obs = latent.event_indicator.astype(float)
    macro_obs = mixed[:, 4] + cfg.noise_std["macro"] * rngs[4].standard_normal(n)

    return {
        "storage_curve": DeskObservation(
            components={
                "price": price + sc_noise_p,
                "balance": balance + sc_noise_b,
            },
            stale_mask=stale_false,
        ),
        "supply": DeskObservation(
            components={"supply": supply_obs, "supply_level": latent.supply},
            stale_mask=stale_false,
        ),
        "demand": DeskObservation(
            components={"demand": demand_obs, "demand_level": latent.demand},
            stale_mask=stale_false,
        ),
        "geopolitics": DeskObservation(
            components={
                "event_indicator": indicator_obs,
                "event_intensity": intensity_obs,
                "event_intensity_raw": latent.event_intensity,
            },
            stale_mask=stale_false,
        ),
        "macro": DeskObservation(
            components={"xi": macro_obs, "xi_level": latent.xi},
            stale_mask=stale_false,
        ),
    }


def _build_realistic(
    latent: LatentPath, cfg: ObservationConfig, seed: int
) -> dict[str, DeskObservation]:
    """Phase C: Phase-B leakage + regime-dependent mixing + chatter +
    missingness + publication lag. We build on top of _build_leakage and
    then layer the contamination factors on each desk's output."""
    base = _build_leakage(latent, cfg, seed)
    n = latent.n_days
    rng_chatter = _rng_for(seed, 200)
    rng_staleness = _rng_for(seed, 201)
    chatter = cfg.chatter_amplitude * rng_chatter.standard_normal(n)

    # Shared macro chatter is applied during event_driven regimes only
    # (plan §A: "shared rumour-driven misinformation" in event regimes).
    is_event = np.array([r == "event_driven" for r in latent.regimes.labels], dtype=bool)
    chatter_active = np.where(is_event, chatter, 0.0)

    out: dict[str, DeskObservation] = {}
    for desk_name, obs in base.items():
        # Apply chatter to each component (additive signal-level contamination)
        contaminated = {k: v + chatter_active for k, v in obs.components.items()}
        # Publication lag
        lag = cfg.publication_lag.get(desk_name, 0)
        if lag > 0:
            contaminated = {k: _apply_lag(v, lag) for k, v in contaminated.items()}
        # Missingness: per-day bernoulli; stale days zero out the signal and
        # flag the stale mask so desks can gate them out.
        stale_prob = cfg.staleness_prob.get(desk_name, 0.0)
        stale_mask = rng_staleness.random(n) < stale_prob
        if stale_mask.any():
            for k in contaminated:
                contaminated[k] = np.where(stale_mask, np.nan, contaminated[k])

        out[desk_name] = DeskObservation(
            components=contaminated, stale_mask=stale_mask, lag_days=lag
        )
    return out
