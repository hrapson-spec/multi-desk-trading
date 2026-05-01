"""Controller decision: pure function of (regime, weights, params, forecasts).

Spec §8.2 decision flow (literal):
  1. Read current RegimeLabel (argmax of regime_probabilities).
  2. Look up the weight row for the regime.
  3. Compute combined_signal = sum(weight × desk_forecast.point_estimate)
     across all (desk, target) in the weight row.
  4. Apply §8.2a linear sizing:
     position_size = clip(k_regime × combined_signal, ±pos_limit_regime)
  5. Emit a Decision event with full provenance.

Staleness discipline: forecasts with staleness=True are excluded from the
combined_signal sum but the Controller still emits a Decision. If every
contributing desk is stale, combined_signal = 0 and position_size = 0 —
the "no-trade" state under a fully-stale catalogue.

Capability-claim debit: §8.2 specifies combined_signal as a raw weight ×
point_estimate sum. For desks whose point_estimate is an absolute
target-variable value (e.g. a predicted price), this sum has the units of
that target rather than a dimensionless signal. Phase 1 accepts this
literal interpretation; signal-normalisation against emission-time
references (e.g. predicted log-return) is a v1.x refinement that should
not require a contracts/v1 bump.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import duckdb
import numpy as np

from contracts.v1 import Decision, Forecast, Provenance, RegimeLabel
from persistence.db import get_latest_controller_params, get_latest_signal_weights


@dataclass
class Controller:
    """Stateless Controller wrapper around a DB connection.

    Holds no runtime state between calls; every decide() is a fresh read.
    """

    conn: duckdb.DuckDBPyConnection
    controller_name: str = "controller"

    # ------------------------------------------------------------------
    # Provenance
    # ------------------------------------------------------------------

    def _provenance(self, regime_label: RegimeLabel, params_artefact: str) -> Provenance:
        # Controller provenance is thin: it records which regime label and
        # which parameter version informed this decision. Model name and
        # version are pinned because the decision logic itself is v1 spec.
        return Provenance(
            desk_name=self.controller_name,
            model_name="linear_regime_conditional",
            model_version="1.0.0",
            input_snapshot_hash=_hash_text(f"{regime_label.regime_id}|{params_artefact}"),
            spec_hash="0" * 64,
            code_commit="0" * 40,
        )

    # ------------------------------------------------------------------
    # Decision flow
    # ------------------------------------------------------------------

    def decide(
        self,
        *,
        now_utc: datetime,
        regime_label: RegimeLabel,
        recent_forecasts: dict[tuple[str, str], Forecast],
    ) -> Decision:
        """Apply §8.2 / §8.2a. recent_forecasts keyed by (desk, target)."""
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")

        weights = get_latest_signal_weights(self.conn, regime_label.regime_id)
        params = get_latest_controller_params(self.conn, regime_label.regime_id)
        if params is None:
            raise RuntimeError(
                f"no ControllerParams for regime {regime_label.regime_id!r}; "
                "seed cold-start first (spec §14.8)"
            )
        if not weights:
            raise RuntimeError(
                f"no SignalWeights for regime {regime_label.regime_id!r}; "
                "seed cold-start first (spec §14.8)"
            )

        combined_signal = 0.0
        contributing_ids: list[str] = []
        for row in weights:
            key = (row["desk_name"], row["target_variable"])
            f = recent_forecasts.get(key)
            if f is None:
                continue
            if f.staleness:
                continue
            w = float(row["weight"])
            # v1.14: exclude retired desks (weight=0) from contributing_ids.
            # A zero weight means the desk was retired via §7.2 auto-retire
            # or v1.7 feed-reliability retirement; its forecast contributes
            # 0 to combined_signal but must not leak into attribution /
            # audit trails. Without this guard, Shapley on same-target
            # desks would misattribute under the zero-weight case.
            if w == 0.0:
                continue
            combined_signal += w * float(f.point_estimate)
            contributing_ids.append(f.forecast_id)

        raw = float(params["k_regime"]) * combined_signal
        limit = float(params["pos_limit_regime"])
        position_size = float(np.clip(raw, -limit, limit))

        return Decision(
            decision_id=str(uuid.uuid4()),
            emission_ts_utc=now_utc,
            regime_id=regime_label.regime_id,
            combined_signal=float(combined_signal),
            position_size=position_size,
            input_forecast_ids=contributing_ids,
            provenance=self._provenance(
                regime_label=regime_label,
                params_artefact=str(params["validation_artefact"]),
            ),
        )


# ---------------------------------------------------------------------------


def _hash_text(s: str) -> str:
    import hashlib

    return hashlib.sha256(s.encode("utf-8")).hexdigest()
