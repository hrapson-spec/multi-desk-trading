"""Day-1 cold-start seeding for the Controller (spec §14.8).

seed_cold_start writes a uniform SignalWeight per (regime, desk, target) and
one matching ControllerParams per regime before the first Controller
invocation. All rows carry validation_artefact="cold_start".

Invariants enforced here (not the DB):
  - promotion_ts_utc is microsecond-precision and identical within a single
    seed_cold_start call (§14.8).
  - lexicographic weight_id / params_id ordering guarantees deterministic
    reads under same-timestamp collisions; the helper reuses uuid4() which
    gives ~122 bits of entropy per row, so collisions are vanishing but
    tie-break still works (§8.3 tie-break rule).
  - uniform weight = 1 / n_desks_signing_off; if zero desks are supplied
    the function refuses (there is no sensible cold-start divisor).
"""

from __future__ import annotations

import uuid
from datetime import datetime

import duckdb

from contracts.v1 import ControllerParams, SignalWeight
from persistence.db import insert_controller_params, insert_signal_weight

# Pre-registered conservative Day-1 position cap. A real deployment would
# pin this via config; the default is low enough that any linear sizing
# before the first promotion cannot take a large directional bet.
DEFAULT_COLD_START_LIMIT: float = 1.0


def seed_cold_start(
    conn: duckdb.DuckDBPyConnection,
    *,
    desks: list[tuple[str, str]],
    regime_ids: list[str],
    boot_ts: datetime,
    default_cold_start_limit: float = DEFAULT_COLD_START_LIMIT,
    k_regime: float = 1.0,
) -> tuple[list[SignalWeight], list[ControllerParams]]:
    """Seed uniform weights + params for each regime. Returns what was written.

    Args:
        conn: DuckDB connection.
        desks: List of (desk_name, target_variable) tuples that have passed
            deployment sign-off. Cold-start covers exactly these; adding a
            desk later is a non-cold-start promotion event (§8.3).
        regime_ids: All regime labels the classifier may emit at boot time
            (minimum: the classifier's default label, typically regime_boot).
        boot_ts: Microsecond-precision datetime.now(tz=UTC) at Controller init.
        default_cold_start_limit: Per-regime pos_limit; ≥ 0 per
            ControllerParams.
        k_regime: Per-regime sizing multiplier. Default 1.0.
    """
    if not desks:
        raise ValueError("seed_cold_start requires at least one desk")
    if not regime_ids:
        raise ValueError("seed_cold_start requires at least one regime_id")
    if boot_ts.tzinfo is None:
        raise ValueError("boot_ts must be timezone-aware (spec §14.8)")

    uniform_weight = 1.0 / len(desks)
    weights_written: list[SignalWeight] = []
    params_written: list[ControllerParams] = []

    for regime in regime_ids:
        for desk_name, target in desks:
            w = SignalWeight(
                weight_id=str(uuid.uuid4()),
                regime_id=regime,
                desk_name=desk_name,
                target_variable=target,
                weight=uniform_weight,
                promotion_ts_utc=boot_ts,
                validation_artefact="cold_start",
            )
            insert_signal_weight(conn, w)
            weights_written.append(w)
        cp = ControllerParams(
            params_id=str(uuid.uuid4()),
            regime_id=regime,
            k_regime=k_regime,
            pos_limit_regime=default_cold_start_limit,
            promotion_ts_utc=boot_ts,
            validation_artefact="cold_start",
        )
        insert_controller_params(conn, cp)
        params_written.append(cp)

    return weights_written, params_written
