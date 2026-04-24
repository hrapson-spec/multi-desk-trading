"""MBP-10 depth-aware simulated-fill drill for S4-2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from v2.s4_0.market_data import MarketDataDepth, MBPSnapshot, fill_claim_limit


class FillSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(frozen=True)
class MBP10Order:
    order_id: str
    symbol: str
    side: FillSide
    quantity: float
    limit_price: float | None = None


@dataclass(frozen=True)
class FillSlice:
    level: int
    price: float
    quantity: float

    def as_dict(self) -> dict[str, float | int]:
        return {
            "level": self.level,
            "price": self.price,
            "quantity": self.quantity,
        }


@dataclass(frozen=True)
class MBP10FillResult:
    order_id: str
    symbol: str
    side: FillSide
    requested_quantity: float
    filled_quantity: float
    residual_quantity: float
    average_fill_price: float | None
    top_of_book_price: float | None
    slippage_vs_top: float | None
    levels_consumed: int
    slices: tuple[FillSlice, ...]
    errors: tuple[str, ...] = ()

    @property
    def fully_filled(self) -> bool:
        return self.filled_quantity > 0 and self.residual_quantity == 0

    @property
    def partially_filled(self) -> bool:
        return self.filled_quantity > 0 and self.residual_quantity > 0

    @property
    def unfilled(self) -> bool:
        return self.filled_quantity == 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "residual_quantity": self.residual_quantity,
            "average_fill_price": self.average_fill_price,
            "top_of_book_price": self.top_of_book_price,
            "slippage_vs_top": self.slippage_vs_top,
            "levels_consumed": self.levels_consumed,
            "slices": [item.as_dict() for item in self.slices],
            "errors": list(self.errors),
        }


@dataclass(frozen=True)
class MBP10DrillReport:
    results: tuple[MBP10FillResult, ...]
    book_validation_errors: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    queue_position_claimed: bool
    report_hash: str

    @property
    def orders_total(self) -> int:
        return len(self.results)

    @property
    def orders_filled(self) -> int:
        return sum(1 for result in self.results if result.fully_filled)

    @property
    def orders_partially_filled(self) -> int:
        return sum(1 for result in self.results if result.partially_filled)

    @property
    def orders_unfilled(self) -> int:
        return sum(1 for result in self.results if result.unfilled)

    @property
    def requested_quantity(self) -> float:
        return sum(result.requested_quantity for result in self.results)

    @property
    def filled_quantity(self) -> float:
        return sum(result.filled_quantity for result in self.results)

    @property
    def residual_quantity(self) -> float:
        return sum(result.residual_quantity for result in self.results)

    @property
    def fill_ratio(self) -> float:
        if self.requested_quantity == 0:
            return 0.0
        return self.filled_quantity / self.requested_quantity

    @property
    def average_fill_price(self) -> float | None:
        if self.filled_quantity == 0:
            return None
        notional = sum(
            result.filled_quantity * float(result.average_fill_price)
            for result in self.results
            if result.average_fill_price is not None
        )
        return notional / self.filled_quantity

    @property
    def average_slippage_vs_top(self) -> float | None:
        filled = [result for result in self.results if result.slippage_vs_top is not None]
        quantity = sum(result.filled_quantity for result in filled)
        if quantity == 0:
            return None
        total = sum(
            result.filled_quantity * float(result.slippage_vs_top)
            for result in filled
        )
        return total / quantity

    @property
    def max_depth_consumed(self) -> int:
        return max((result.levels_consumed for result in self.results), default=0)

    @property
    def levels_consumed_total(self) -> int:
        return sum(result.levels_consumed for result in self.results)

    @property
    def ok(self) -> bool:
        return (
            not self.book_validation_errors
            and not any(result.errors for result in self.results)
            and not self.queue_position_claimed
        )

    def metrics(self) -> dict[str, Any]:
        return {
            "orders_total": self.orders_total,
            "orders_filled": self.orders_filled,
            "orders_partially_filled": self.orders_partially_filled,
            "orders_unfilled": self.orders_unfilled,
            "requested_quantity": self.requested_quantity,
            "filled_quantity": self.filled_quantity,
            "residual_quantity": self.residual_quantity,
            "fill_ratio": self.fill_ratio,
            "average_fill_price": self.average_fill_price,
            "average_slippage_vs_top": self.average_slippage_vs_top,
            "max_depth_consumed": self.max_depth_consumed,
            "levels_consumed_total": self.levels_consumed_total,
            "book_validation_errors": list(self.book_validation_errors),
            "prohibited_claims": list(self.prohibited_claims),
            "queue_position_claimed": self.queue_position_claimed,
            "ok": self.ok,
            "report_hash": self.report_hash,
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "metrics": self.metrics(),
            "results": [result.as_dict() for result in self.results],
        }


def simulate_mbp10_fill(order: MBP10Order, book: MBPSnapshot) -> MBP10FillResult:
    errors = _validate_order(order)
    book_errors = _validate_book(book)
    if errors or book_errors:
        return MBP10FillResult(
            order_id=order.order_id,
            symbol=order.symbol,
            side=order.side,
            requested_quantity=order.quantity,
            filled_quantity=0.0,
            residual_quantity=max(order.quantity, 0.0),
            average_fill_price=None,
            top_of_book_price=None,
            slippage_vs_top=None,
            levels_consumed=0,
            slices=(),
            errors=(*errors, *book_errors),
        )

    remaining = order.quantity
    slices: list[FillSlice] = []
    top = _top_price(order.side, book)
    for index, level in enumerate(book.levels, start=1):
        price = level.ask_price if order.side == FillSide.BUY else level.bid_price
        available = level.ask_size if order.side == FillSide.BUY else level.bid_size
        if available <= 0:
            continue
        if not _passes_limit(order, price):
            break
        quantity = min(remaining, available)
        if quantity > 0:
            slices.append(FillSlice(level=index, price=price, quantity=quantity))
            remaining -= quantity
        if remaining == 0:
            break

    filled = sum(item.quantity for item in slices)
    average = _average_price(slices)
    slippage = _slippage(order.side, average, top) if average is not None else None
    return MBP10FillResult(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        requested_quantity=order.quantity,
        filled_quantity=filled,
        residual_quantity=remaining,
        average_fill_price=average,
        top_of_book_price=top,
        slippage_vs_top=slippage,
        levels_consumed=max((item.level for item in slices), default=0),
        slices=tuple(slices),
    )


def run_mbp10_drill(
    orders: list[MBP10Order],
    books: dict[str, MBPSnapshot],
) -> MBP10DrillReport:
    book_errors: list[str] = []
    for symbol, book in sorted(books.items()):
        for error in _validate_book(book):
            book_errors.append(f"{symbol}: {error}")

    results = tuple(
        simulate_mbp10_fill(order, books[order.symbol])
        if order.symbol in books
        else _missing_book_result(order)
        for order in orders
    )
    claim = fill_claim_limit(MarketDataDepth.MBP10)
    payload = {
        "orders": [_order_payload(order) for order in orders],
        "books": {
            symbol: _book_payload(book)
            for symbol, book in sorted(books.items())
        },
        "results": [result.as_dict() for result in results],
        "book_validation_errors": book_errors,
        "prohibited_claims": list(claim.prohibited_claims),
        "queue_position_claimed": False,
    }
    return MBP10DrillReport(
        results=results,
        book_validation_errors=tuple(book_errors),
        prohibited_claims=claim.prohibited_claims,
        queue_position_claimed=False,
        report_hash=_sha256_json(payload),
    )


def _validate_order(order: MBP10Order) -> tuple[str, ...]:
    errors: list[str] = []
    if order.quantity <= 0:
        errors.append("order quantity must be > 0")
    if order.limit_price is not None and order.limit_price <= 0:
        errors.append("limit_price must be > 0")
    return tuple(errors)


def _validate_book(book: MBPSnapshot) -> tuple[str, ...]:
    try:
        book.validate(max_depth=10)
    except ValueError as exc:
        return (str(exc),)
    return ()


def _passes_limit(order: MBP10Order, price: float) -> bool:
    if order.limit_price is None:
        return True
    if order.side == FillSide.BUY:
        return price <= order.limit_price
    return price >= order.limit_price


def _top_price(side: FillSide, book: MBPSnapshot) -> float:
    first = book.levels[0]
    return first.ask_price if side == FillSide.BUY else first.bid_price


def _average_price(slices: list[FillSlice]) -> float | None:
    quantity = sum(item.quantity for item in slices)
    if quantity == 0:
        return None
    notional = sum(item.quantity * item.price for item in slices)
    return notional / quantity


def _slippage(side: FillSide, average: float | None, top: float) -> float | None:
    if average is None:
        return None
    if side == FillSide.BUY:
        return average - top
    return top - average


def _missing_book_result(order: MBP10Order) -> MBP10FillResult:
    return MBP10FillResult(
        order_id=order.order_id,
        symbol=order.symbol,
        side=order.side,
        requested_quantity=order.quantity,
        filled_quantity=0.0,
        residual_quantity=max(order.quantity, 0.0),
        average_fill_price=None,
        top_of_book_price=None,
        slippage_vs_top=None,
        levels_consumed=0,
        slices=(),
        errors=(f"missing MBP-10 book for symbol {order.symbol}",),
    )


def _order_payload(order: MBP10Order) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": order.side.value,
        "quantity": order.quantity,
        "limit_price": order.limit_price,
    }


def _book_payload(book: MBPSnapshot) -> list[dict[str, float]]:
    return [
        {
            "bid_price": level.bid_price,
            "bid_size": level.bid_size,
            "ask_price": level.ask_price,
            "ask_size": level.ask_size,
        }
        for level in book.levels
    ]


def _sha256_json(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    ).hexdigest()
