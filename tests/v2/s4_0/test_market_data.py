"""Market-data depth and fill-claim limit tests."""

from __future__ import annotations

import pytest

from v2.s4_0.market_data import (
    MarketDataDepth,
    MBPLevel,
    MBPSnapshot,
    TopOfBook,
    fill_claim_limit,
)


def test_fill_claim_limits_prevent_overclaiming_queue_accuracy_on_mbp10():
    trades = fill_claim_limit(MarketDataDepth.TRADES)
    mbp10 = fill_claim_limit(MarketDataDepth.MBP10)
    mbo = fill_claim_limit(MarketDataDepth.MBO)

    assert trades.allowed_claim == "last_sale_replay_only"
    assert "quote_or_book_aware_fill_quality" in trades.prohibited_claims
    assert mbp10.allowed_claim == "level_2_depth_aware_fill_approximation"
    assert "queue_position_accuracy" in mbp10.prohibited_claims
    assert mbo.allowed_claim == "order_level_queue_reconstruction_subject_to_vendor_semantics"


def test_top_of_book_rejects_crossed_book():
    with pytest.raises(ValueError, match="crossed"):
        TopOfBook(bid_price=75.10, bid_size=1, ask_price=75.00, ask_size=1).validate()


def test_mbp_snapshot_validates_depth_and_monotonic_levels():
    MBPSnapshot(
        levels=(
            MBPLevel(bid_price=75.00, bid_size=10, ask_price=75.01, ask_size=11),
            MBPLevel(bid_price=74.99, bid_size=12, ask_price=75.02, ask_size=13),
        )
    ).validate()

    with pytest.raises(ValueError, match="bid levels"):
        MBPSnapshot(
            levels=(
                MBPLevel(bid_price=75.00, bid_size=10, ask_price=75.01, ask_size=11),
                MBPLevel(bid_price=75.01, bid_size=12, ask_price=75.02, ask_size=13),
            )
        ).validate()
