"""CL contract-roll policy tests for S4-0."""

from __future__ import annotations

from datetime import date

import pytest

from v2.s4_0.contract_roll import (
    CLContract,
    ExchangeCalendar,
    RollPolicy,
    cl_last_trade_date,
    roll_status,
    select_front_next,
)


def test_cl_last_trade_date_uses_normal_25th_anchor():
    calendar = ExchangeCalendar()

    assert cl_last_trade_date(date(2026, 7, 1), calendar=calendar) == date(2026, 6, 22)


def test_cl_last_trade_date_adjusts_holiday_25th_anchor():
    calendar = ExchangeCalendar(holidays=frozenset({date(2026, 5, 25)}))

    assert cl_last_trade_date(date(2026, 6, 1), calendar=calendar) == date(2026, 5, 19)


def test_contract_symbol_parser_accepts_one_or_two_digit_year_codes():
    calendar = ExchangeCalendar()

    assert CLContract.from_symbol("CLM6", calendar=calendar).delivery_month == date(2026, 6, 1)
    assert CLContract.from_symbol("CLM26", calendar=calendar).delivery_month == date(
        2026, 6, 1
    )


def test_roll_status_blocks_new_trades_and_forces_flat_before_delivery_window():
    calendar = ExchangeCalendar(holidays=frozenset({date(2026, 5, 25)}))
    policy = RollPolicy(no_new_trades_buffer_business_days=5, must_be_flat_buffer_business_days=3)
    contract = CLContract.from_symbol("CLM6", calendar=calendar)

    status = roll_status(contract, as_of_date=date(2026, 5, 14), calendar=calendar, policy=policy)

    assert status.last_trade_date == date(2026, 5, 19)
    assert status.no_new_trades_from == date(2026, 5, 12)
    assert status.must_be_flat_by == date(2026, 5, 14)
    assert status.can_open_new_trade is False
    assert status.in_no_new_trades_window is True
    assert status.in_forced_flat_window is True


def test_select_front_next_rolls_past_contract_inside_freeze_window():
    calendar = ExchangeCalendar(holidays=frozenset({date(2026, 5, 25)}))
    policy = RollPolicy(no_new_trades_buffer_business_days=5, must_be_flat_buffer_business_days=3)
    contracts = [
        CLContract.from_symbol(symbol, calendar=calendar)
        for symbol in ("CLM6", "CLN6", "CLQ6")
    ]

    normal = select_front_next(
        contracts,
        as_of_date=date(2026, 5, 11),
        calendar=calendar,
        policy=policy,
        source_of_truth="synthetic_contract_metadata",
    )
    rolling = select_front_next(
        contracts,
        as_of_date=date(2026, 5, 14),
        calendar=calendar,
        policy=policy,
        source_of_truth="synthetic_contract_metadata",
    )

    assert normal.front.symbol == "CLM6"
    assert normal.next.symbol == "CLN6"
    assert rolling.front.symbol == "CLN6"
    assert rolling.next.symbol == "CLQ6"
    assert rolling.receipt()["front_definition"] == (
        "nearest listed CL contract tradeable under project roll policy"
    )


def test_select_front_next_rejects_when_no_next_contract_listed():
    calendar = ExchangeCalendar()
    policy = RollPolicy()
    contracts = [CLContract.from_symbol("CLN6", calendar=calendar)]

    with pytest.raises(ValueError, match="no listed CL next contract"):
        select_front_next(
            contracts,
            as_of_date=date(2026, 5, 1),
            calendar=calendar,
            policy=policy,
            source_of_truth="synthetic_contract_metadata",
        )
