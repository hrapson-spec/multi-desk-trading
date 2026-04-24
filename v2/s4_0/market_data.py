"""Market-data depth abstractions and fill-claim limits for S4 testing."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MarketDataDepth(StrEnum):
    TRADES = "trades"
    MBP1 = "mbp_1"
    MBP10 = "mbp_10"
    MBO = "mbo"
    PCAP = "pcap"


@dataclass(frozen=True)
class FillClaimLimit:
    depth: MarketDataDepth
    allowed_claim: str
    prohibited_claims: tuple[str, ...] = ()


def fill_claim_limit(depth: MarketDataDepth) -> FillClaimLimit:
    limits = {
        MarketDataDepth.TRADES: FillClaimLimit(
            depth=depth,
            allowed_claim="last_sale_replay_only",
            prohibited_claims=("quote_or_book_aware_fill_quality",),
        ),
        MarketDataDepth.MBP1: FillClaimLimit(
            depth=depth,
            allowed_claim="top_of_book_spread_aware_fill_approximation",
        ),
        MarketDataDepth.MBP10: FillClaimLimit(
            depth=depth,
            allowed_claim="level_2_depth_aware_fill_approximation",
            prohibited_claims=("queue_position_accuracy",),
        ),
        MarketDataDepth.MBO: FillClaimLimit(
            depth=depth,
            allowed_claim="order_level_queue_reconstruction_subject_to_vendor_semantics",
        ),
        MarketDataDepth.PCAP: FillClaimLimit(
            depth=depth,
            allowed_claim="raw_feed_handler_validation",
        ),
    }
    return limits[depth]


@dataclass(frozen=True)
class TopOfBook:
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float

    def validate(self) -> None:
        if self.bid_price <= 0 or self.ask_price <= 0:
            raise ValueError("book prices must be positive")
        if self.bid_size < 0 or self.ask_size < 0:
            raise ValueError("book sizes must be non-negative")
        if self.bid_price > self.ask_price:
            raise ValueError("crossed top-of-book")


@dataclass(frozen=True)
class MBPLevel:
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float


@dataclass(frozen=True)
class MBPSnapshot:
    levels: tuple[MBPLevel, ...]

    def validate(self, *, max_depth: int = 10) -> None:
        if not self.levels:
            raise ValueError("MBP snapshot must contain at least one level")
        if len(self.levels) > max_depth:
            raise ValueError(f"MBP snapshot exceeds max_depth={max_depth}")
        previous_bid: float | None = None
        previous_ask: float | None = None
        for level in self.levels:
            TopOfBook(
                bid_price=level.bid_price,
                bid_size=level.bid_size,
                ask_price=level.ask_price,
                ask_size=level.ask_size,
            ).validate()
            if previous_bid is not None and level.bid_price > previous_bid:
                raise ValueError("MBP bid levels must be non-increasing")
            if previous_ask is not None and level.ask_price < previous_ask:
                raise ValueError("MBP ask levels must be non-decreasing")
            previous_bid = level.bid_price
            previous_ask = level.ask_price
