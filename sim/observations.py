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

    # Per-desk measurement noise std (clean mode; also baseline for other modes)
    noise_std: dict[str, float] = field(
        default_factory=lambda: {
            "storage_curve": 0.05,  # roughly $4 std on an $80 price
            "supply": 0.05,
            "demand": 0.05,
            "geopolitics": 0.02,
            "macro": 0.02,
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


@dataclass(frozen=True)
class ObservationChannels:
    """Dispatcher returning `channels[desk_name] → DeskObservation`.

    Construct with a LatentPath + mode + config; call `.by_desk[name]`.
    """

    by_desk: dict[str, DeskObservation]
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

        return cls(
            by_desk=by_desk,
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

    stale_false = np.zeros(n, dtype=bool)
    return {
        "storage_curve": DeskObservation(
            components={
                "price": price + sc_noise_price,
                "balance": balance + sc_noise_balance,
            },
            stale_mask=stale_false,
        ),
        "supply": DeskObservation(
            components={"supply": supply + s_noise},
            stale_mask=stale_false,
        ),
        "demand": DeskObservation(
            components={"demand": demand + d_noise},
            stale_mask=stale_false,
        ),
        "geopolitics": DeskObservation(
            components={
                "event_indicator": events + g_noise_ind,
                "event_intensity": intensity + g_noise_int,
            },
            stale_mask=stale_false,
        ),
        "macro": DeskObservation(
            components={"xi": xi + m_noise},
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
    """Mix on STANDARDIZED factors (z-scores), rescale back to each factor's
    native scale. This keeps the leakage proportional to the receiving
    factor's magnitude, not dominated by the largest-scale source."""
    n = latent.n_days
    n_factors = 5
    latent_matrix = _latent_vector(latent)  # (n, 5)
    z, mu, sigma = _standardize(latent_matrix)
    m = _mixing_matrix(cfg.leakage_strength)

    # Mix in standardized space
    z_mixed = z @ m.T  # (n, 5)
    # Rescale each column back to its own desk's native scale
    desk_signals = z_mixed * sigma + mu

    rngs = [_rng_for(seed, 100 + k) for k in range(n_factors)]
    stale_false = np.zeros(n, dtype=bool)

    sc_log_price_mixed = desk_signals[:, 0]
    sc_price = np.exp(sc_log_price_mixed)
    sc_noise_p = cfg.noise_std["storage_curve"] * sc_price * rngs[0].standard_normal(n)
    sc_noise_b = cfg.noise_std["storage_curve"] * rngs[0].standard_normal(n)
    # Balance channel: mix on standardized balance (derive from mixed supply/demand)
    sc_balance = (desk_signals[:, 1] - desk_signals[:, 2]) + sc_noise_b

    supply_obs = desk_signals[:, 1] + cfg.noise_std["supply"] * rngs[1].standard_normal(n)
    demand_obs = desk_signals[:, 2] + cfg.noise_std["demand"] * rngs[2].standard_normal(n)
    intensity_obs = desk_signals[:, 3] + cfg.noise_std["geopolitics"] * rngs[3].standard_normal(n)
    # Event indicator is a {0,1} arrival channel; leakage in the magnitude
    # channel (event_intensity) is enough to contaminate geopolitics without
    # corrupting the arrival timestamps themselves.
    indicator_obs = latent.event_indicator.astype(float)
    macro_obs = desk_signals[:, 4] + cfg.noise_std["macro"] * rngs[4].standard_normal(n)

    return {
        "storage_curve": DeskObservation(
            components={"price": sc_price + sc_noise_p, "balance": sc_balance},
            stale_mask=stale_false,
        ),
        "supply": DeskObservation(components={"supply": supply_obs}, stale_mask=stale_false),
        "demand": DeskObservation(components={"demand": demand_obs}, stale_mask=stale_false),
        "geopolitics": DeskObservation(
            components={
                "event_indicator": indicator_obs,
                "event_intensity": intensity_obs,
            },
            stale_mask=stale_false,
        ),
        "macro": DeskObservation(components={"xi": macro_obs}, stale_mask=stale_false),
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
