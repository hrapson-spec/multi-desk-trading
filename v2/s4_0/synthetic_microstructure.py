"""Synthetic tick and order-book fixture validation for S4-1."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from v2.s4_0.market_data import (
    MarketDataDepth,
    MBPSnapshot,
    TopOfBook,
    fill_claim_limit,
)
from v2.s4_0.replay_quality import ReplayTick, TickQualityReport, analyze_tick_quality


@dataclass(frozen=True)
class SyntheticMarketEvent:
    symbol: str
    ts_event: datetime
    ts_recv: datetime | None
    vendor_row_number: int
    exchange_sequence_number: int | None
    trade_price: float | None = None
    trade_size: float | None = None
    top_of_book: TopOfBook | None = None
    mbp_snapshot: MBPSnapshot | None = None

    def replay_tick(self) -> ReplayTick:
        return ReplayTick(
            symbol=self.symbol,
            ts_event=self.ts_event,
            ts_recv=self.ts_recv,
            vendor_row_number=self.vendor_row_number,
            exchange_sequence_number=self.exchange_sequence_number,
        )

    def event_id(self) -> str:
        return _sha256_json(self.as_payload())

    def as_payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ts_event": self.ts_event.isoformat(),
            "ts_recv": self.ts_recv.isoformat() if self.ts_recv else None,
            "vendor_row_number": self.vendor_row_number,
            "exchange_sequence_number": self.exchange_sequence_number,
            "trade_price": self.trade_price,
            "trade_size": self.trade_size,
            "top_of_book": _top_payload(self.top_of_book),
            "mbp_snapshot": _mbp_payload(self.mbp_snapshot),
        }


@dataclass(frozen=True)
class SyntheticFixtureReport:
    depth: MarketDataDepth
    input_rows: int
    expected_symbols: tuple[str, ...]
    observed_symbols: tuple[str, ...]
    event_ids: tuple[str, ...]
    source_hash: str
    tick_quality: TickQualityReport
    allowed_fill_claim: str
    prohibited_fill_claims: tuple[str, ...]
    errors: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.errors and not self.tick_quality.has_material_gap

    def as_dict(self) -> dict[str, Any]:
        return {
            "depth": self.depth.value,
            "input_rows": self.input_rows,
            "expected_symbols": list(self.expected_symbols),
            "observed_symbols": list(self.observed_symbols),
            "event_ids": list(self.event_ids),
            "source_hash": self.source_hash,
            "tick_quality": self.tick_quality.as_dict(),
            "allowed_fill_claim": self.allowed_fill_claim,
            "prohibited_fill_claims": list(self.prohibited_fill_claims),
            "errors": list(self.errors),
            "ok": self.ok,
        }


def evaluate_synthetic_fixture(
    events: list[SyntheticMarketEvent],
    *,
    expected_symbols: set[str],
    depth: MarketDataDepth,
) -> SyntheticFixtureReport:
    errors: list[str] = []
    if not events:
        errors.append("synthetic fixture has no events")

    tick_quality = analyze_tick_quality(
        [event.replay_tick() for event in events],
        expected_symbols=expected_symbols,
        sequence_scope="global",
    )
    _validate_depth_claim(depth, errors)
    for event in events:
        _validate_event(event, depth=depth, errors=errors)

    ordered = sorted(events, key=lambda event: event.replay_tick().ordering_key())
    event_ids = tuple(event.event_id() for event in ordered)
    claim = fill_claim_limit(depth)
    return SyntheticFixtureReport(
        depth=depth,
        input_rows=len(events),
        expected_symbols=tuple(sorted(expected_symbols)),
        observed_symbols=tuple(sorted({event.symbol for event in events})),
        event_ids=event_ids,
        source_hash=_sha256_json(event_ids),
        tick_quality=tick_quality,
        allowed_fill_claim=claim.allowed_claim,
        prohibited_fill_claims=claim.prohibited_claims,
        errors=tuple(errors),
    )


def _validate_depth_claim(depth: MarketDataDepth, errors: list[str]) -> None:
    if depth == MarketDataDepth.MBO:
        errors.append("full MBO order-level reconstruction is not implemented")
    if depth == MarketDataDepth.PCAP:
        errors.append("PCAP/raw-feed replay is not implemented")


def _validate_event(
    event: SyntheticMarketEvent,
    *,
    depth: MarketDataDepth,
    errors: list[str],
) -> None:
    if event.trade_price is not None and event.trade_price <= 0:
        errors.append(f"{event.symbol} row {event.vendor_row_number}: trade_price must be > 0")
    if event.trade_size is not None and event.trade_size < 0:
        errors.append(f"{event.symbol} row {event.vendor_row_number}: trade_size must be >= 0")

    if depth == MarketDataDepth.TRADES and event.trade_price is None:
        errors.append(f"{event.symbol} row {event.vendor_row_number}: trade_price is required")
    if depth == MarketDataDepth.MBP1 and event.top_of_book is None:
        errors.append(f"{event.symbol} row {event.vendor_row_number}: top_of_book is required")
    if depth == MarketDataDepth.MBP10 and event.mbp_snapshot is None:
        errors.append(f"{event.symbol} row {event.vendor_row_number}: mbp_snapshot is required")

    if event.top_of_book is not None:
        try:
            event.top_of_book.validate()
        except ValueError as exc:
            errors.append(f"{event.symbol} row {event.vendor_row_number}: {exc}")
        else:
            _validate_trade_inside_top(event, event.top_of_book, errors)
    if event.mbp_snapshot is not None:
        try:
            event.mbp_snapshot.validate(max_depth=10)
        except ValueError as exc:
            errors.append(f"{event.symbol} row {event.vendor_row_number}: {exc}")
        else:
            first_level = event.mbp_snapshot.levels[0]
            _validate_trade_inside_top(
                event,
                TopOfBook(
                    bid_price=first_level.bid_price,
                    bid_size=first_level.bid_size,
                    ask_price=first_level.ask_price,
                    ask_size=first_level.ask_size,
                ),
                errors,
            )


def _validate_trade_inside_top(
    event: SyntheticMarketEvent,
    top: TopOfBook,
    errors: list[str],
) -> None:
    if event.trade_price is None:
        return
    if event.trade_price < top.bid_price or event.trade_price > top.ask_price:
        errors.append(
            f"{event.symbol} row {event.vendor_row_number}: "
            "trade_price outside top-of-book"
        )


def _top_payload(top: TopOfBook | None) -> dict[str, float] | None:
    if top is None:
        return None
    return {
        "bid_price": top.bid_price,
        "bid_size": top.bid_size,
        "ask_price": top.ask_price,
        "ask_size": top.ask_size,
    }


def _mbp_payload(snapshot: MBPSnapshot | None) -> list[dict[str, float]] | None:
    if snapshot is None:
        return None
    return [
        {
            "bid_price": level.bid_price,
            "bid_size": level.bid_size,
            "ask_price": level.ask_price,
            "ask_size": level.ask_size,
        }
        for level in snapshot.levels
    ]


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()
