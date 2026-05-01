"""Adapter tests (b_t → lots)."""

from __future__ import annotations

import pytest

from v2.execution import AdapterParams, target_lots


def _params(**overrides) -> AdapterParams:
    base: dict = {
        "reference_risk_5d_usd": 100_000.0,
        "contract_multiplier_bbl": 1000.0,  # CL
        "rounding": "nearest",
    }
    base.update(overrides)
    return AdapterParams(**base)


def test_zero_b_gives_zero_lots():
    r = target_lots(b_t=0.0, price=70.0, market_vol_5d=0.04, params=_params())
    assert r.rounded_lots == 0
    assert r.raw_lots == pytest.approx(0.0)


def test_positive_b_positive_lots():
    r = target_lots(b_t=0.5, price=70.0, market_vol_5d=0.04, params=_params())
    # raw = 0.5 · 100_000 / (1000 · 70 · 0.04) = 50_000 / 2800 ≈ 17.857
    assert r.rounded_lots == 18
    assert r.raw_lots == pytest.approx(17.857, rel=1e-3)


def test_negative_b_negative_lots():
    r = target_lots(b_t=-0.5, price=70.0, market_vol_5d=0.04, params=_params())
    assert r.rounded_lots == -18


def test_effective_b_recoverable_from_rounding():
    r = target_lots(b_t=0.5, price=70.0, market_vol_5d=0.04, params=_params())
    # effective_b = 18 · 2800 / 100_000 = 0.504
    assert r.effective_b == pytest.approx(0.504, rel=1e-3)


def test_max_abs_lots_cap_applied():
    r = target_lots(
        b_t=1.0,
        price=70.0,
        market_vol_5d=0.04,
        params=_params(max_abs_lots=5),
    )
    assert r.rounded_lots == 5
    # effective_b is capped at 1.0 (not re-inflated past sleeve).
    assert r.effective_b <= 1.0


def test_floor_rounding():
    r = target_lots(b_t=0.5, price=70.0, market_vol_5d=0.04, params=_params(rounding="floor"))
    assert r.rounded_lots == 17  # floor(17.857)


def test_ceil_rounding_negative_b():
    r = target_lots(b_t=-0.5, price=70.0, market_vol_5d=0.04, params=_params(rounding="ceil"))
    # ceil(-17.857) = -17
    assert r.rounded_lots == -17


def test_mcl_multiplier():
    r = target_lots(
        b_t=0.5,
        price=70.0,
        market_vol_5d=0.04,
        params=_params(contract_multiplier_bbl=100.0),  # MCL
    )
    # raw = 50_000 / 280 ≈ 178.571
    assert r.rounded_lots == 179


def test_b_outside_range_rejected():
    with pytest.raises(ValueError):
        target_lots(b_t=1.5, price=70.0, market_vol_5d=0.04, params=_params())


def test_nonpositive_price_rejected():
    with pytest.raises(ValueError):
        target_lots(b_t=0.5, price=0.0, market_vol_5d=0.04, params=_params())


def test_nonpositive_vol_rejected():
    with pytest.raises(ValueError):
        target_lots(b_t=0.5, price=70.0, market_vol_5d=0.0, params=_params())


def test_invalid_rounding_rejected():
    with pytest.raises(ValueError):
        AdapterParams(
            reference_risk_5d_usd=100_000.0,
            contract_multiplier_bbl=1000.0,
            rounding="banker",
        )
