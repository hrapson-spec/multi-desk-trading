"""Tests for the deterministic event-flag calendar."""

from __future__ import annotations

from datetime import date

import pandas as pd

from v2.ingest.event_calendar import (
    build_event_calendar,
    cl_last_trade_date,
    us_federal_holidays,
)


def test_eia_release_day_normal_wednesday():
    df = build_event_calendar(date(2026, 4, 20), date(2026, 4, 24))
    assert df.loc[pd.Timestamp("2026-04-22"), "is_eia_release_day"] is True or bool(
        df.loc[pd.Timestamp("2026-04-22"), "is_eia_release_day"]
    )
    # Tuesday must be False.
    assert not bool(df.loc[pd.Timestamp("2026-04-21"), "is_eia_release_day"])


def test_eia_release_shifts_when_wednesday_is_holiday():
    """Christmas 2024 fell on a Wednesday — EIA release shifts to Thursday
    per the ``shift_next_business_day`` rule in eia_wpsr.yaml."""
    df = build_event_calendar(date(2024, 12, 22), date(2024, 12, 27))
    assert not bool(df.loc[pd.Timestamp("2024-12-25"), "is_eia_release_day"])
    assert bool(df.loc[pd.Timestamp("2024-12-26"), "is_eia_release_day"])


def test_days_since_eia_release_resets_on_release_day():
    """Within a normal week containing two consecutive Wednesdays, the
    counter rises Wed -> Tue, then resets to 0 on the next Wednesday."""
    df = build_event_calendar(date(2026, 4, 15), date(2026, 4, 30))
    # 2026-04-15 is a Wednesday (release).
    assert df.loc[pd.Timestamp("2026-04-15"), "days_since_eia_release"] == 0
    assert df.loc[pd.Timestamp("2026-04-16"), "days_since_eia_release"] == 1
    assert df.loc[pd.Timestamp("2026-04-21"), "days_since_eia_release"] == 6
    # Next Wednesday resets to 0.
    assert df.loc[pd.Timestamp("2026-04-22"), "days_since_eia_release"] == 0


def test_cot_release_day_friday():
    """COT releases on Fridays (>=15:30 ET). 2026-04-24 is a Friday."""
    df = build_event_calendar(date(2026, 4, 20), date(2026, 4, 26))
    assert bool(df.loc[pd.Timestamp("2026-04-24"), "is_cot_release_day"])
    # Thursday must be False.
    assert not bool(df.loc[pd.Timestamp("2026-04-23"), "is_cot_release_day"])


def test_cl_last_trade_date_for_june_2026_contract():
    """June 2026 CL contract: rule walks back from 25th of preceding month
    (May 25, 2026 = Memorial Day) -> prior business day Fri May 22 -> 3 BD
    before -> Tue May 19."""
    assert cl_last_trade_date(date(2026, 6, 1)) == date(2026, 5, 19)


def test_cl_expiry_and_roll_freeze_window_widths():
    """``is_cl_expiry_window`` covers exactly 3 business days; the
    ``is_roll_freeze_window`` covers exactly 5 business days, both
    immediately BEFORE the LTD."""
    # Pick a calendar window that includes a known LTD.
    ltd = cl_last_trade_date(date(2026, 6, 1))  # 2026-05-19
    df = build_event_calendar(date(2026, 5, 1), date(2026, 5, 31))
    expiry_count = int(df["is_cl_expiry_window"].sum())
    freeze_count = int(df["is_roll_freeze_window"].sum())
    # Across this single-LTD window, expiry has 3 business days, roll
    # freeze has 5. (Multiple LTDs would compound; this window only
    # holds one because the May LTD itself is on the 19th.)
    assert expiry_count == 3
    assert freeze_count == 5
    # The LTD itself is not in the window (window is "before").
    assert not bool(df.loc[pd.Timestamp(ltd), "is_cl_expiry_window"])
    assert not bool(df.loc[pd.Timestamp(ltd), "is_roll_freeze_window"])


def test_us_federal_holiday_calendar_2026():
    """Sanity: New Year's Day, MLK (3rd Mon Jan), Independence Day observed."""
    holidays_2026 = set(us_federal_holidays(2026))
    assert date(2026, 1, 1) in holidays_2026  # New Year's
    assert date(2026, 1, 19) in holidays_2026  # MLK = 3rd Monday of January 2026
    # July 4, 2026 is a Saturday -> observed Friday July 3.
    assert date(2026, 7, 3) in holidays_2026
    # And confirm the build_event_calendar surfaces these as flags.
    df = build_event_calendar(date(2026, 1, 1), date(2026, 1, 31))
    assert bool(df.loc[pd.Timestamp("2026-01-01"), "is_us_holiday"])
    assert bool(df.loc[pd.Timestamp("2026-01-19"), "is_us_holiday"])
    assert not bool(df.loc[pd.Timestamp("2026-01-20"), "is_us_holiday"])
