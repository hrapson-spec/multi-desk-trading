"""Synthetic tick and order-book fixture gate tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from v2.s4_0.market_data import MarketDataDepth, MBPLevel, MBPSnapshot, TopOfBook
from v2.s4_0.synthetic_microstructure import (
    SyntheticMarketEvent,
    evaluate_synthetic_fixture,
)


def _ts(second: int) -> datetime:
    return datetime(2026, 4, 24, 13, 0, second, tzinfo=UTC)


def _event(
    row: int,
    *,
    symbol: str = "CLM6",
    sequence: int | None = None,
    second: int = 0,
    price: float = 75.00,
    top: TopOfBook | None = None,
    mbp: MBPSnapshot | None = None,
) -> SyntheticMarketEvent:
    return SyntheticMarketEvent(
        symbol=symbol,
        ts_event=_ts(second),
        ts_recv=_ts(second) + timedelta(microseconds=1),
        vendor_row_number=row,
        exchange_sequence_number=sequence or row,
        trade_price=price,
        trade_size=1,
        top_of_book=top,
        mbp_snapshot=mbp,
    )


def test_synthetic_mbp1_fixture_is_deterministic_and_claim_limited():
    top = TopOfBook(bid_price=74.99, bid_size=10, ask_price=75.01, ask_size=12)
    events = [
        _event(1, sequence=100, top=top),
        _event(2, sequence=101, top=top),
        _event(3, symbol="CLN6", sequence=102, second=1, price=75.01, top=top),
    ]

    first = evaluate_synthetic_fixture(
        events,
        expected_symbols={"CLM6", "CLN6"},
        depth=MarketDataDepth.MBP1,
    )
    second = evaluate_synthetic_fixture(
        list(reversed(events)),
        expected_symbols={"CLM6", "CLN6"},
        depth=MarketDataDepth.MBP1,
    )

    assert first.ok is True
    assert first.source_hash == second.source_hash
    assert first.event_ids == second.event_ids
    assert first.tick_quality.same_timestamp_groups == 1
    assert first.allowed_fill_claim == "top_of_book_spread_aware_fill_approximation"
    assert first.observed_symbols == ("CLM6", "CLN6")


def test_synthetic_fixture_reports_material_sequence_gap():
    events = [
        _event(1, sequence=1),
        _event(2, sequence=3, second=1),
    ]

    report = evaluate_synthetic_fixture(
        events,
        expected_symbols={"CLM6"},
        depth=MarketDataDepth.TRADES,
    )

    assert report.ok is False
    assert report.tick_quality.sequence_gap_count == 1
    assert report.tick_quality.findings[0].severity == "SEV1"


def test_synthetic_mbp1_rejects_crossed_book_and_outside_trade():
    events = [
        _event(
            1,
            price=75.20,
            top=TopOfBook(bid_price=75.10, bid_size=1, ask_price=75.00, ask_size=1),
        )
    ]

    report = evaluate_synthetic_fixture(
        events,
        expected_symbols={"CLM6"},
        depth=MarketDataDepth.MBP1,
    )

    assert report.ok is False
    assert any("crossed top-of-book" in error for error in report.errors)


def test_synthetic_mbp10_validates_depth_and_prohibits_queue_claim():
    events = [
        _event(
            1,
            mbp=MBPSnapshot(
                levels=(
                    MBPLevel(bid_price=75.00, bid_size=10, ask_price=75.01, ask_size=11),
                    MBPLevel(bid_price=75.01, bid_size=12, ask_price=75.02, ask_size=13),
                )
            ),
        )
    ]

    report = evaluate_synthetic_fixture(
        events,
        expected_symbols={"CLM6"},
        depth=MarketDataDepth.MBP10,
    )

    assert report.ok is False
    assert "queue_position_accuracy" in report.prohibited_fill_claims
    assert any("bid levels" in error for error in report.errors)


def test_synthetic_mbo_is_explicitly_deferred():
    report = evaluate_synthetic_fixture(
        [_event(1)],
        expected_symbols={"CLM6"},
        depth=MarketDataDepth.MBO,
    )

    assert report.ok is False
    assert report.allowed_fill_claim == (
        "order_level_queue_reconstruction_subject_to_vendor_semantics"
    )
    assert report.errors == ("full MBO order-level reconstruction is not implemented",)
