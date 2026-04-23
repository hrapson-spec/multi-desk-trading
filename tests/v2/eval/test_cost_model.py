"""Two-scenario cost-stress tests."""

from __future__ import annotations

import numpy as np
import pytest

from v2.eval import CostParams, CostScenario, apply_costs


def _series(n: int, pos_path: list[float], gross: list[float]) -> tuple:
    pb = np.array(pos_path[:-1], dtype=float)
    pa = np.array(pos_path[1:], dtype=float)
    gr = np.array(gross, dtype=float)
    rv = np.full(n, 0.04)
    return pb, pa, gr, rv


def test_zero_turnover_zero_cost():
    pos = [0.5] * 11  # constant position, no trades
    pb, pa, gr, rv = _series(10, pos, [0.0] * 10)
    for params in (CostParams.optimistic_default(), CostParams.pessimistic_default()):
        rep = apply_costs(
            positions_before=pb,
            positions_after=pa,
            gross_returns=gr,
            realised_vols=rv,
            params=params,
        )
        assert rep.cost_total == 0.0
        assert rep.turnover_total == 0.0


def test_pessimistic_costs_exceed_optimistic_on_same_path():
    pos = [0.0, 1.0, 0.0, 1.0, 0.0, 1.0]  # high turnover
    pb, pa, gr, rv = _series(5, pos, [0.01] * 5)
    opt = apply_costs(
        positions_before=pb,
        positions_after=pa,
        gross_returns=gr,
        realised_vols=rv,
        params=CostParams.optimistic_default(),
    )
    pess = apply_costs(
        positions_before=pb,
        positions_after=pa,
        gross_returns=gr,
        realised_vols=rv,
        params=CostParams.pessimistic_default(),
    )
    assert pess.cost_total > opt.cost_total
    assert pess.net_return_total < opt.net_return_total


def test_turnover_sum_equals_abs_delta_sum():
    pos = [0.0, 0.5, 0.5, 1.0, 0.2]
    pb, pa, gr, rv = _series(4, pos, [0.0] * 4)
    rep = apply_costs(
        positions_before=pb,
        positions_after=pa,
        gross_returns=gr,
        realised_vols=rv,
        params=CostParams.optimistic_default(),
    )
    expected = float(np.abs(pa - pb).sum())
    assert rep.turnover_total == pytest.approx(expected)


def test_gross_return_uses_pre_trade_position():
    # Hold 0.5 throughout, earn 1 tick of 0.02 gross return.
    pb = np.array([0.5])
    pa = np.array([0.5])
    gr = np.array([0.02])
    rv = np.array([0.04])
    rep = apply_costs(
        positions_before=pb,
        positions_after=pa,
        gross_returns=gr,
        realised_vols=rv,
        params=CostParams.optimistic_default(),
    )
    assert rep.gross_return_total == pytest.approx(0.5 * 0.02)
    assert rep.cost_total == 0.0
    assert rep.net_return_total == pytest.approx(0.01)


def test_shape_mismatch_rejected():
    with pytest.raises(ValueError):
        apply_costs(
            positions_before=np.zeros(5),
            positions_after=np.zeros(6),
            gross_returns=np.zeros(5),
            realised_vols=np.zeros(5),
            params=CostParams.optimistic_default(),
        )


def test_scenario_labelled_on_report():
    pb, pa, gr, rv = _series(2, [0.0, 0.5, 0.0], [0.01, 0.01])
    rep = apply_costs(
        positions_before=pb,
        positions_after=pa,
        gross_returns=gr,
        realised_vols=rv,
        params=CostParams.optimistic_default(),
    )
    assert rep.scenario == CostScenario.OPTIMISTIC
