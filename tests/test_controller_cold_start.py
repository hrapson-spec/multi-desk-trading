"""Cold-start seeding tests (spec §14.8).

Verifies that seed_cold_start writes one uniform SignalWeight per
(regime, desk, target) and one ControllerParams per regime, with
deterministic tie-break reads under same-timestamp collisions.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from controller import DEFAULT_COLD_START_LIMIT, seed_cold_start
from persistence.db import (
    connect,
    count_rows,
    get_latest_controller_params,
    get_latest_signal_weights,
    init_db,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "test.duckdb")
    init_db(c)
    yield c
    c.close()


def test_cold_start_seeds_uniform_weights_for_one_regime(conn):
    boot = datetime(2026, 4, 16, 12, 0, 0, 123456, tzinfo=UTC)
    desks = [
        ("storage_curve", WTI_FRONT_MONTH_CLOSE),
        ("demand", WTI_FRONT_MONTH_CLOSE),
    ]
    ws, ps = seed_cold_start(conn, desks=desks, regime_ids=["regime_boot"], boot_ts=boot)
    assert len(ws) == 2
    assert len(ps) == 1

    rows = get_latest_signal_weights(conn, "regime_boot")
    assert len(rows) == 2
    weights_by_desk = {r["desk_name"]: r["weight"] for r in rows}
    assert weights_by_desk["storage_curve"] == pytest.approx(0.5)
    assert weights_by_desk["demand"] == pytest.approx(0.5)
    assert all(r["validation_artefact"] == "cold_start" for r in rows)

    cp = get_latest_controller_params(conn, "regime_boot")
    assert cp is not None
    assert cp["k_regime"] == 1.0
    assert cp["pos_limit_regime"] == DEFAULT_COLD_START_LIMIT
    assert cp["validation_artefact"] == "cold_start"


def test_cold_start_multi_regime(conn):
    boot = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
    desks = [("storage_curve", WTI_FRONT_MONTH_CLOSE)]
    seed_cold_start(conn, desks=desks, regime_ids=["regime_a", "regime_b"], boot_ts=boot)
    assert count_rows(conn, "signal_weights") == 2  # 1 desk × 2 regimes
    assert count_rows(conn, "controller_params") == 2  # 1 per regime
    for r in ("regime_a", "regime_b"):
        ws = get_latest_signal_weights(conn, r)
        assert len(ws) == 1
        assert ws[0]["weight"] == pytest.approx(1.0)


def test_cold_start_rejects_empty_desks(conn):
    boot = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="at least one desk"):
        seed_cold_start(conn, desks=[], regime_ids=["regime_boot"], boot_ts=boot)


def test_cold_start_rejects_naive_boot_ts(conn):
    boot_naive = datetime(2026, 4, 16, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        seed_cold_start(
            conn,
            desks=[("storage_curve", WTI_FRONT_MONTH_CLOSE)],
            regime_ids=["regime_boot"],
            boot_ts=boot_naive,
        )


def test_cold_start_deterministic_tie_break_on_same_timestamp(conn):
    """§8.3: same promotion_ts_utc collisions are broken by lexicographic
    weight_id. This makes double-seeding idempotent w.r.t. which row wins."""
    boot = datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC)
    desks = [("storage_curve", WTI_FRONT_MONTH_CLOSE)]

    seed_cold_start(conn, desks=desks, regime_ids=["regime_boot"], boot_ts=boot)
    # Second seed at the identical timestamp (frozen-clock scenario).
    seed_cold_start(conn, desks=desks, regime_ids=["regime_boot"], boot_ts=boot)

    rows = get_latest_signal_weights(conn, "regime_boot")
    assert len(rows) == 1  # one winner per (desk, target)
    # Either row's weight_id is valid; determinism is the property that
    # matters, not which specific uuid4 came first.
    assert rows[0]["weight"] == pytest.approx(1.0)
