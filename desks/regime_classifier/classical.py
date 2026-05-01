"""Regime classifiers (plan §A; spec §10).

Two classes live here:

  - `GroundTruthRegimeClassifier` (Phase A v0.1): pass-through of the
    simulator's ground-truth regime label. Used to isolate
    desk/Controller/attribution testing from classifier quality under
    the DERAIL isolation principle.
  - `HMMRegimeClassifier` (v0.3): data-driven Gaussian HMM fitted on
    market-price log-returns via hmmlearn. By default it selects the
    regime count from a bounded range using BIC, so the shipped path is
    no longer fixed-K.

The HMM's regime IDs are opaque integers (`hmm_regime_0`, ...): they do
NOT align with the simulator's ground-truth labels
(`equilibrium`, `supply_dominated`, etc.) because the HMM has no way to
know which latent state corresponds to which economic regime. Controller
weight matrices are keyed on `regime_id` strings, so the weight matrix is
re-keyed to the HMM's opaque IDs; a real deployment would use
label-matching (e.g. Hungarian algorithm on forecast distributions) to
align.

The spec's full HDP-HMM remains a future model-family option, but the
root fixed-K weakness is closed here: the default classifier now selects
K in a capped range [2, 6] from the observed data without changing the
Controller contract.
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
# HMMRegimeClassifier (v0.3)
# ---------------------------------------------------------------------------

_HMM_NAME = "gaussian_hmm_adaptive_k_bic_v0.3"
_HMM_MIN_STATES = 2
_HMM_MAX_STATES = 6


@dataclass
class HMMRegimeClassifier:
    """Adaptive-K Gaussian HMM over market-price log-returns.

    Fit with `fit(market_price_train)`; after fitting, call
    `regime_label_at(channels, i, now_utc)` to get a RegimeLabel at
    index `i`. The classifier computes posterior probabilities using
    hmmlearn's forward algorithm on the log-return sequence
    `log(market_price[:i+1])`, so the label at index `i` only depends
    on observations up to and including that index (no look-ahead).

    By default the classifier fits candidate HMMs for K in
    `[min_states, max_states]` and chooses the best BIC score. Passing
    `n_states` forces a fixed-K fit, which remains useful for narrow
    tests but is no longer the default deployment path.

    Regime IDs are opaque strings `hmm_regime_0`, ...,
    `hmm_regime_{K-1}`. A real deployment would align them to semantic
    labels via a post-fit matching step (out of scope here).
    """

    n_states: int | None = None
    min_states: int = _HMM_MIN_STATES
    max_states: int = _HMM_MAX_STATES
    n_iter: int = 30
    seed: int = 0

    _model: object | None = field(default=None, init=False, repr=False)
    _fitted: bool = field(default=False, init=False)
    _train_hash: str = field(default="", init=False)
    _active_n_states: int = field(default=0, init=False)

    @staticmethod
    def _n_hmm_params(n_states: int, n_features: int) -> int:
        """Approximate free-parameter count for BIC under diag covariance."""
        startprob_params = n_states - 1
        transition_params = n_states * (n_states - 1)
        mean_params = n_states * n_features
        covariance_params = n_states * n_features
        return startprob_params + transition_params + mean_params + covariance_params

    def _candidate_state_counts(self, n_train_obs: int) -> list[int]:
        if self.n_states is not None:
            if self.n_states < 2:
                raise ValueError(f"n_states must be ≥ 2; got {self.n_states}")
            if n_train_obs < self.n_states * 10:
                raise ValueError(
                    f"need ≥ {self.n_states * 10} training observations; got {n_train_obs}"
                )
            return [self.n_states]
        if self.min_states < 2:
            raise ValueError(f"min_states must be ≥ 2; got {self.min_states}")
        if self.max_states < self.min_states:
            raise ValueError(
                f"max_states must be ≥ min_states; got {self.max_states} < {self.min_states}"
            )
        if n_train_obs < self.min_states * 10:
            raise ValueError(
                f"need ≥ {self.min_states * 10} training observations; got {n_train_obs}"
            )
        max_fit_states = min(self.max_states, max(self.min_states, n_train_obs // 10))
        return list(range(self.min_states, max_fit_states + 1))

    def fit(self, market_price_train: np.ndarray) -> None:
        """Fit HMM on training log-returns. Deterministic under the given seed."""
        import hashlib

        from hmmlearn import hmm

        log_rets = np.diff(np.log(market_price_train)).reshape(-1, 1)
        candidate_states = self._candidate_state_counts(len(market_price_train))
        best_model: object | None = None
        best_k: int | None = None
        best_bic: float | None = None

        for k in candidate_states:
            model = hmm.GaussianHMM(
                n_components=k,
                covariance_type="diag",
                n_iter=self.n_iter,
                random_state=self.seed + 1009 * k,
                init_params="stmc",
                params="stmc",
            )
            model.fit(log_rets)
            log_likelihood = float(model.score(log_rets))
            bic = -2.0 * log_likelihood + self._n_hmm_params(k, log_rets.shape[1]) * float(
                np.log(len(log_rets))
            )
            if (
                best_bic is None
                or bic < best_bic - 1e-12
                or (abs(bic - best_bic) <= 1e-12 and best_k is not None and k < best_k)
            ):
                best_model = model
                best_k = k
                best_bic = bic

        if best_model is None or best_k is None:
            raise RuntimeError("failed to fit any HMM candidate")

        self._model = best_model
        self._fitted = True
        self._active_n_states = best_k
        # Deterministic fingerprint over fitted params
        h = hashlib.sha256()
        h.update(np.asarray([best_k], dtype=np.int64).tobytes())
        h.update(best_model.startprob_.tobytes())
        h.update(best_model.transmat_.tobytes())
        h.update(best_model.means_.tobytes())
        h.update(best_model.covars_.tobytes())
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
            model_version="0.3.0",
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
        probs = {
            self._regime_str(k): float(probs_vec[k]) for k in range(self._active_n_states)
        }
        # Transition row for the argmax state (hmmlearn stores transmat_[i, j] = P(j|i))
        trans_row = self._model.transmat_[argmax_k]
        trans = {self._regime_str(k): float(trans_row[k]) for k in range(self._active_n_states)}
        return RegimeLabel(
            classification_ts_utc=now_utc,
            regime_id=regime_id,
            regime_probabilities=probs,
            transition_probabilities=trans,
            classifier_provenance=self._provenance(),
        )

    @property
    def active_n_states(self) -> int:
        if self._fitted and self._active_n_states > 0:
            return self._active_n_states
        if self.n_states is not None:
            return self.n_states
        return self.max_states

    def active_regime_ids(self) -> list[str]:
        return [self._regime_str(k) for k in range(self.active_n_states)]

    @staticmethod
    def all_regime_ids(max_states: int = _HMM_MAX_STATES) -> list[str]:
        return [f"hmm_regime_{k}" for k in range(max_states)]
