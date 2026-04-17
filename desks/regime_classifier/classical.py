"""Regime classifier — Phase A ground-truth pass-through (plan §A).

**Capability-claim debit** (explicit): this is NOT a real classifier.
Phase A validates the desk + Controller + attribution architecture
*under a known regime-label channel*, so a pass-through classifier
isolates the desk-architecture test from classifier-quality testing
(DERAIL isolation principle from the user's Q2 research).

A real HMM / HDP-HMM classifier per spec §10 is a v0.2 follow-up. When
it lands, the integration tests swap this class for the real one and
assert the architecture continues to pass gates under noisier labels.

Interface: `regime_label_at(channels, i, now_utc)` returns a
RegimeLabel whose `regime_id` is the simulator's ground-truth label at
index i (channels.latent_path.regimes.labels[i]). Probabilities are
degenerate: 1.0 on the ground-truth regime, 0.0 everywhere else.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from contracts.v1 import Provenance, RegimeLabel
from sim.regimes import REGIMES

if TYPE_CHECKING:
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
