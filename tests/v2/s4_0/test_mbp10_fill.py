"""MBP-10 simulated-fill drill tests."""

from __future__ import annotations

import pytest

from v2.s4_0.market_data import MBPLevel, MBPSnapshot
from v2.s4_0.mbp10_fill import FillSide, MBP10Order, run_mbp10_drill


def _book() -> MBPSnapshot:
    return MBPSnapshot(
        levels=(
            MBPLevel(bid_price=74.99, bid_size=10, ask_price=75.01, ask_size=10),
            MBPLevel(bid_price=74.98, bid_size=20, ask_price=75.02, ask_size=20),
            MBPLevel(bid_price=74.97, bid_size=30, ask_price=75.03, ask_size=30),
        )
    )


def test_mbp10_drill_reports_all_fill_metrics():
    orders = [
        MBP10Order("buy_full", "CLM6", FillSide.BUY, quantity=15),
        MBP10Order("sell_full", "CLM6", FillSide.SELL, quantity=12, limit_price=74.98),
        MBP10Order("buy_partial", "CLM6", FillSide.BUY, quantity=100, limit_price=75.02),
        MBP10Order("sell_unfilled", "CLM6", FillSide.SELL, quantity=5, limit_price=75.10),
    ]

    report = run_mbp10_drill(orders, {"CLM6": _book()})
    metrics = report.metrics()

    assert report.ok is True
    assert metrics["orders_total"] == 4
    assert metrics["orders_filled"] == 2
    assert metrics["orders_partially_filled"] == 1
    assert metrics["orders_unfilled"] == 1
    assert metrics["requested_quantity"] == 132
    assert metrics["filled_quantity"] == 57
    assert metrics["residual_quantity"] == 75
    assert metrics["fill_ratio"] == pytest.approx(57 / 132)
    assert metrics["average_fill_price"] == pytest.approx(4275.56 / 57)
    assert metrics["average_slippage_vs_top"] == pytest.approx(0.27 / 57)
    assert metrics["max_depth_consumed"] == 2
    assert metrics["levels_consumed_total"] == 6
    assert metrics["book_validation_errors"] == []
    assert metrics["prohibited_claims"] == ["queue_position_accuracy"]
    assert metrics["queue_position_claimed"] is False
    assert metrics["report_hash"] == report.report_hash


def test_mbp10_drill_is_deterministic_for_same_inputs():
    orders = [
        MBP10Order("buy_full", "CLM6", FillSide.BUY, quantity=15),
        MBP10Order("sell_full", "CLM6", FillSide.SELL, quantity=12),
    ]

    first = run_mbp10_drill(orders, {"CLM6": _book()})
    second = run_mbp10_drill(orders, {"CLM6": _book()})

    assert first.report_hash == second.report_hash
    assert first.metrics() == second.metrics()


def test_mbp10_limit_price_blocks_levels_and_records_partial_fill():
    report = run_mbp10_drill(
        [MBP10Order("buy_limited", "CLM6", FillSide.BUY, quantity=100, limit_price=75.01)],
        {"CLM6": _book()},
    )
    result = report.results[0]

    assert result.partially_filled is True
    assert result.filled_quantity == 10
    assert result.residual_quantity == 90
    assert result.levels_consumed == 1
    assert result.average_fill_price == 75.01


def test_mbp10_invalid_book_and_order_are_reported_as_errors():
    invalid_book = MBPSnapshot(
        levels=(
            MBPLevel(bid_price=75.00, bid_size=10, ask_price=75.01, ask_size=10),
            MBPLevel(bid_price=75.01, bid_size=20, ask_price=75.02, ask_size=20),
        )
    )
    report = run_mbp10_drill(
        [MBP10Order("bad_qty", "CLM6", FillSide.BUY, quantity=0)],
        {"CLM6": invalid_book},
    )

    assert report.ok is False
    assert report.book_validation_errors == ("CLM6: MBP bid levels must be non-increasing",)
    assert report.results[0].errors == (
        "order quantity must be > 0",
        "MBP bid levels must be non-increasing",
    )


def test_mbp10_missing_book_is_reported_per_order():
    report = run_mbp10_drill(
        [MBP10Order("missing", "CLN6", FillSide.BUY, quantity=1)],
        {"CLM6": _book()},
    )

    assert report.ok is False
    assert report.results[0].unfilled is True
    assert report.results[0].errors == ("missing MBP-10 book for symbol CLN6",)
