"""CL front/next contract selection and roll-window rules for S4 tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

_MONTH_CODES = {
    "F": 1,
    "G": 2,
    "H": 3,
    "J": 4,
    "K": 5,
    "M": 6,
    "N": 7,
    "Q": 8,
    "U": 9,
    "V": 10,
    "X": 11,
    "Z": 12,
}


@dataclass(frozen=True)
class ExchangeCalendar:
    """Minimal business-day calendar for S4 roll fixtures.

    Formal S4 should use vendor/exchange metadata. This class exists to make
    the synthetic roll tests deterministic and explicit.
    """

    holidays: frozenset[date] = frozenset()

    def is_business_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def prior_business_day(self, day: date) -> date:
        current = day - timedelta(days=1)
        while not self.is_business_day(current):
            current -= timedelta(days=1)
        return current

    def business_days_before(self, day: date, n: int) -> date:
        if n < 0:
            raise ValueError("n must be >= 0")
        current = day
        for _ in range(n):
            current = self.prior_business_day(current)
        return current

    def business_days_until(self, start: date, end: date) -> int:
        """Count business days in (start, end]."""
        if end < start:
            return -self.business_days_until(end, start)
        current = start
        count = 0
        while current < end:
            current += timedelta(days=1)
            if self.is_business_day(current):
                count += 1
        return count


@dataclass(frozen=True)
class RollPolicy:
    type: str = "pre_expiry_buffer"
    no_new_trades_buffer_business_days: int = 5
    must_be_flat_buffer_business_days: int = 3

    def __post_init__(self) -> None:
        if self.no_new_trades_buffer_business_days < 0:
            raise ValueError("no_new_trades_buffer_business_days must be >= 0")
        if self.must_be_flat_buffer_business_days < 0:
            raise ValueError("must_be_flat_buffer_business_days must be >= 0")
        if self.must_be_flat_buffer_business_days > self.no_new_trades_buffer_business_days:
            raise ValueError("must_be_flat buffer cannot be earlier than no_new_trades buffer")


@dataclass(frozen=True)
class CLContract:
    symbol: str
    delivery_month: date
    last_trade_date: date

    @classmethod
    def from_symbol(
        cls,
        symbol: str,
        *,
        calendar: ExchangeCalendar,
        year_digit_base: int = 2020,
    ) -> CLContract:
        if not symbol.startswith("CL") or len(symbol) < 4:
            raise ValueError(f"not a CL contract symbol: {symbol!r}")
        month_code = symbol[2].upper()
        if month_code not in _MONTH_CODES:
            raise ValueError(f"unknown CL month code in symbol: {symbol!r}")
        year_digit = symbol[3:]
        if not year_digit.isdigit():
            raise ValueError(f"unknown CL year code in symbol: {symbol!r}")
        year = _parse_contract_year(year_digit, year_digit_base=year_digit_base)
        delivery_month = date(year, _MONTH_CODES[month_code], 1)
        return cls(
            symbol=symbol,
            delivery_month=delivery_month,
            last_trade_date=cl_last_trade_date(delivery_month, calendar=calendar),
        )


@dataclass(frozen=True)
class RollStatus:
    symbol: str
    as_of_date: date
    last_trade_date: date
    no_new_trades_from: date
    must_be_flat_by: date
    business_days_to_last_trade: int
    expired: bool
    in_no_new_trades_window: bool
    in_forced_flat_window: bool
    can_open_new_trade: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "as_of_date": self.as_of_date.isoformat(),
            "last_trade_date": self.last_trade_date.isoformat(),
            "no_new_trades_from": self.no_new_trades_from.isoformat(),
            "must_be_flat_by": self.must_be_flat_by.isoformat(),
            "business_days_to_last_trade": self.business_days_to_last_trade,
            "expired": self.expired,
            "in_no_new_trades_window": self.in_no_new_trades_window,
            "in_forced_flat_window": self.in_forced_flat_window,
            "can_open_new_trade": self.can_open_new_trade,
        }


@dataclass(frozen=True)
class FrontNextSelection:
    front: CLContract
    next: CLContract
    front_status: RollStatus
    next_status: RollStatus
    policy: RollPolicy
    source_of_truth: str

    def receipt(self) -> dict[str, Any]:
        return {
            "front_contract": self.front.symbol,
            "next_contract": self.next.symbol,
            "front_definition": "nearest listed CL contract tradeable under project roll policy",
            "next_definition": "listed CL contract immediately after front contract",
            "source_of_truth": self.source_of_truth,
            "roll_policy": {
                "type": self.policy.type,
                "no_new_trades_buffer_business_days": (
                    self.policy.no_new_trades_buffer_business_days
                ),
                "must_be_flat_buffer_business_days": (
                    self.policy.must_be_flat_buffer_business_days
                ),
            },
            "front_status": self.front_status.as_dict(),
            "next_status": self.next_status.as_dict(),
        }


def cl_last_trade_date(delivery_month: date, *, calendar: ExchangeCalendar) -> date:
    """Return CL last trade date for a delivery month fixture.

    CL terminates three business days before the 25th calendar day of the
    month before delivery. If that 25th is not a business day, use the business
    day immediately preceding it as the anchor.
    """
    if delivery_month.day != 1:
        delivery_month = delivery_month.replace(day=1)
    prior_month_year = delivery_month.year if delivery_month.month > 1 else delivery_month.year - 1
    prior_month = delivery_month.month - 1 if delivery_month.month > 1 else 12
    anchor = date(prior_month_year, prior_month, 25)
    if not calendar.is_business_day(anchor):
        anchor = calendar.prior_business_day(anchor)
    return calendar.business_days_before(anchor, 3)


def _parse_contract_year(year_code: str, *, year_digit_base: int) -> int:
    if len(year_code) == 1:
        decade = (year_digit_base // 10) * 10
        year = decade + int(year_code)
        if year < year_digit_base - 5:
            year += 10
        return year
    if len(year_code) == 2:
        century = (year_digit_base // 100) * 100
        year = century + int(year_code)
        if year < year_digit_base - 50:
            year += 100
        return year
    raise ValueError(f"unsupported CL year code: {year_code!r}")


def roll_status(
    contract: CLContract,
    *,
    as_of_date: date,
    calendar: ExchangeCalendar,
    policy: RollPolicy,
) -> RollStatus:
    no_new = calendar.business_days_before(
        contract.last_trade_date, policy.no_new_trades_buffer_business_days
    )
    flat = calendar.business_days_before(
        contract.last_trade_date, policy.must_be_flat_buffer_business_days
    )
    expired = as_of_date > contract.last_trade_date
    in_no_new = as_of_date >= no_new
    in_flat = as_of_date >= flat
    return RollStatus(
        symbol=contract.symbol,
        as_of_date=as_of_date,
        last_trade_date=contract.last_trade_date,
        no_new_trades_from=no_new,
        must_be_flat_by=flat,
        business_days_to_last_trade=calendar.business_days_until(
            as_of_date, contract.last_trade_date
        ),
        expired=expired,
        in_no_new_trades_window=in_no_new,
        in_forced_flat_window=in_flat,
        can_open_new_trade=not expired and not in_no_new,
    )


def select_front_next(
    contracts: list[CLContract],
    *,
    as_of_date: date,
    calendar: ExchangeCalendar,
    policy: RollPolicy,
    source_of_truth: str,
) -> FrontNextSelection:
    listed = sorted(contracts, key=lambda contract: contract.delivery_month)
    statuses = {
        contract.symbol: roll_status(
            contract, as_of_date=as_of_date, calendar=calendar, policy=policy
        )
        for contract in listed
    }
    front_index: int | None = None
    for index, contract in enumerate(listed):
        if statuses[contract.symbol].can_open_new_trade:
            front_index = index
            break
    if front_index is None:
        raise ValueError("no tradeable CL front contract under roll policy")
    next_index = front_index + 1
    if next_index >= len(listed):
        raise ValueError("no listed CL next contract after selected front")
    front = listed[front_index]
    next_contract = listed[next_index]
    return FrontNextSelection(
        front=front,
        next=next_contract,
        front_status=statuses[front.symbol],
        next_status=statuses[next_contract.symbol],
        policy=policy,
        source_of_truth=source_of_truth,
    )
