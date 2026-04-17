"""Regime classifiers (plan §A; spec §10).

Two classes live here:

  - `GroundTruthRegimeClassifier` (Phase A v0.1): pass-through of the
    simulator's ground-truth regime label. Used to isolate
    desk/Controller/attribution testing from classifier quality under
    the DERAIL isolation principle.
  - `HMMRegimeClassifier` (v0.2): data-driven 4-state Gaussian HMM
    fitted on market-price log-returns via hmmlearn. Emits `RegimeLabel`
    with soft posterior probabilities and a data-driven `regime_id` that
    the Controller's `regime_id = argmax(probabilities)` path already
    consumes without code changes.

The HMM's regime IDs are opaque integers (`hmm_regime_0` … `hmm_regime_3`)
— they do NOT align with the simulator's ground truth labels
(`equilibrium`, `supply_dominated`, etc.) because the HMM has no way to
know which latent state corresponds to which economic regime. Controller
weight matrices are keyed on `regime_id` strings, so at Phase A v0.2 the
weight matrix is re-keyed to the HMM's opaque IDs; a real deployment
would use label-matching (e.g. Hungarian algorithm on forecast
distributions) to align.

**Capability-claim debit (remaining in v0.2)**: real deployment wants an
HDP-HMM per spec §10 (non-parametric regime count, capped at 6 per §8.5).
The v0.2 Gaussian HMM uses a fixed K=4 matching the simulator's known
regime count; HDP-HMM lands in v0.3.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np

from contracts.v1 import Provenance, RegimeLabel
from sim.regimes import REGIMES

if TYPE_CHECKING:
    from hmmlearn import hmm  # noqa: F401

    from sim.observations import ObservationChannels

_CLASSIFIER_NAME = "ground_truth_passthrough_v0.1"
_CLASSIFIER_DEBIT = "phase_a_isolation:hdp_hmm_deferred_to_v0.2"


@dataclass
class GroundTruthRegimeClassifier:
    """Reads simulator regime ground truth; emits degenerate-probability
    RegimeLabel.

    Replace with a real HMM in v0.2 without changing the calling code —
    the interface of `regime_label_at(channels, i, now_utc)` is stable.
    """

    def fingerprint(self) -> str:
        """Deterministic identifier for provenance. Pass-through classifier
        has no fitted parameters; a stable constant is sufficient."""
        return "sha256:" + hashlib.sha256(_CLASSIFIER_NAME.encode("utf-8")).hexdigest()

    def _provenance(self) -> Provenance:
        fp_hex = self.fingerprint().encode("utf-8").hex()
        snapshot_hash = (fp_hex + "0" * 64)[:64]
        return Provenance(
            desk_name="regime_classifier",
            model_name=_CLASSIFIER_NAME,
            model_version="0.1.0",
            input_snapshot_hash=snapshot_hash,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    def regime_label_at(
        self, channels: ObservationChannels, i: int, now_utc: datetime
    ) -> RegimeLabel:
        """Read ground truth from the underlying LatentPath.

        Raises IndexError if i is out of range; that is a programming error
        on the caller's side (the Controller should never ask for an index
        outside the generated path).
        """
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        regime_id = channels.latent_path.regimes.regime_at(i)
        # Degenerate distribution: 1.0 on ground truth, 0.0 elsewhere.
        probs = {r: (1.0 if r == regime_id else 0.0) for r in REGIMES}
        # Transition probs are also degenerate — we don't model transitions
        # in the pass-through; a real classifier would emit useful values.
        trans = {r: (1.0 if r == regime_id else 0.0) for r in REGIMES}
        return RegimeLabel(
            classification_ts_utc=now_utc,
            regime_id=regime_id,
            regime_probabilities=probs,
            transition_probabilities=trans,
            classifier_provenance=self._provenance(),
        )


# ---------------------------------------------------------------------------
# HMMRegimeClassifier (v0.2)
# ---------------------------------------------------------------------------

_HMM_NAME = "gaussian_hmm_k4_v0.2"
_HMM_DEBIT = "hdp_hmm_deferred_to_v0.3"
_HMM_N_STATES = 4  # matches sim/regimes.py REGIMES count


@dataclass
class HMMRegimeClassifier:
    """4-state Gaussian HMM over market-price log-returns.

    Fit with `fit(market_price_train)`; after fitting, call
    `regime_label_at(channels, i, now_utc)` to get a RegimeLabel at
    index `i`. The classifier computes posterior probabilities using
    hmmlearn's forward algorithm on the log-return sequence
    `log(market_price[:i+1])`, so the label at index `i` only depends
    on observations up to and including that index (no look-ahead).

    Regime IDs are opaque strings `hmm_regime_0` … `hmm_regime_3`. A
    real deployment would align them to semantic labels via a post-fit
    matching step (out of scope for v0.2).
    """

    n_states: int = _HMM_N_STATES
    n_iter: int = 30
    seed: int = 0

    _model: object | None = field(default=None, init=False, repr=False)
    _fitted: bool = field(default=False, init=False)
    _train_hash: str = field(default="", init=False)

    def fit(self, market_price_train: np.ndarray) -> None:
        """Fit HMM on training log-returns. Deterministic under the given seed."""
        import hashlib

        from hmmlearn import hmm

        if len(market_price_train) < self.n_states * 10:
            raise ValueError(
                f"need ≥ {self.n_states * 10} training observations; got {len(market_price_train)}"
            )

        log_rets = np.diff(np.log(market_price_train)).reshape(-1, 1)
        model = hmm.GaussianHMM(
            n_components=self.n_states,
            covariance_type="diag",
            n_iter=self.n_iter,
            random_state=self.seed,
            init_params="stmc",
            params="stmc",
        )
        model.fit(log_rets)
        self._model = model
        self._fitted = True
        # Deterministic fingerprint over fitted params
        h = hashlib.sha256()
        h.update(model.startprob_.tobytes())
        h.update(model.transmat_.tobytes())
        h.update(model.means_.tobytes())
        h.update(model.covars_.tobytes())
        self._train_hash = h.hexdigest()

    def fingerprint(self) -> str:
        if not self._fitted:
            return "unfit"
        return "sha256:" + self._train_hash

    def _provenance(self) -> Provenance:
        fp_hex = self.fingerprint().encode("utf-8").hex()
        snapshot_hash = (fp_hex + "0" * 64)[:64]
        return Provenance(
            desk_name="regime_classifier",
            model_name=_HMM_NAME,
            model_version="0.2.0",
            input_snapshot_hash=snapshot_hash,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    def _regime_str(self, k: int) -> str:
        return f"hmm_regime_{k}"

    def regime_label_at(
        self, channels: ObservationChannels, i: int, now_utc: datetime
    ) -> RegimeLabel:
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        if not self._fitted or self._model is None:
            raise RuntimeError("HMMRegimeClassifier not fitted; call .fit() first")
        if i < 1:
            raise ValueError(f"i must be ≥ 1 to derive a log-return; got {i}")

        # Causal posterior: use observations up to and including index i.
        prices = channels.market_price[: i + 1]
        log_rets = np.diff(np.log(prices)).reshape(-1, 1)
        # predict_proba returns smoothed (forward-backward) probabilities;
        # we want causal (forward-only). Use _compute_log_likelihood +
        # forward pass directly. hmmlearn exposes this via .score_samples.
        _, posteriors = self._model.score_samples(log_rets)
        # posteriors[-1] is P(state_t | x_1..x_t) — the filtered posterior at t.
        probs_vec = posteriors[-1]  # (n_states,)
        argmax_k = int(np.argmax(probs_vec))
        regime_id = self._regime_str(argmax_k)
        probs = {self._regime_str(k): float(probs_vec[k]) for k in range(self.n_states)}
        # Transition row for the argmax state (hmmlearn stores transmat_[i, j] = P(j|i))
        trans_row = self._model.transmat_[argmax_k]
        trans = {self._regime_str(k): float(trans_row[k]) for k in range(self.n_states)}
        return RegimeLabel(
            classification_ts_utc=now_utc,
            regime_id=regime_id,
            regime_probabilities=probs,
            transition_probabilities=trans,
            classifier_provenance=self._provenance(),
        )

    @staticmethod
    def all_regime_ids() -> list[str]:
        return [f"hmm_regime_{k}" for k in range(_HMM_N_STATES)]
