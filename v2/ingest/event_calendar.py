"""Deterministic event-flag generator for the v2 public-data synthesis layer.

This module produces a daily ``DataFrame`` keyed by date with a fixed schema
of event flags (EIA WPSR release, CFTC COT release, CL expiry/roll windows,
US federal holidays). It is *derived* — not an ingester. It does not call
``PITWriter``; it does not have a manifest entry. Synthesised features
inherit their PIT eligibility from the parent calendars they reference
(see ``v2/pit_store/calendars/event_calendar.yaml``).

Holiday rules are encoded programmatically (no ``pandas_market_calendars``
dependency at v2.0); each holiday is rendered for any year via its
documented calendar rule, then observed-shifted onto the nearest weekday
per US federal-holiday convention.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

# -- US federal holidays ------------------------------------------------------

_WEEKDAY_MON = 0
_WEEKDAY_FRI = 4
_WEEKDAY_SAT = 5
_WEEKDAY_SUN = 6


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the ``n``-th occurrence of ``weekday`` in ``month`` of ``year``."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return date(year, month, 1 + offset + (n - 1) * 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Return the LAST occurrence of ``weekday`` in ``month`` of ``year``."""
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    last = nxt - timedelta(days=1)
    while last.weekday() != weekday:
        last -= timedelta(days=1)
    return last


def _observed(d: date) -> date:
    """Apply the standard US federal observed-holiday rule.

    Saturday -> previous Friday; Sunday -> next Monday. Weekday holidays
    are unchanged.
    """
    if d.weekday() == _WEEKDAY_SAT:
        return d - timedelta(days=1)
    if d.weekday() == _WEEKDAY_SUN:
        return d + timedelta(days=1)
    return d


def us_federal_holidays(year: int) -> list[date]:
    """Return the observed dates of the eleven US federal holidays in ``year``.

    Covered: New Year's Day, MLK Day, Washington's Birthday, Memorial Day,
    Juneteenth, Independence Day, Labor Day, Columbus Day, Veterans Day,
    Thanksgiving, Christmas Day. Each is observed-shifted off weekends.
    """
    rules: list[date] = [
        _observed(date(year, 1, 1)),  # New Year's Day
        _nth_weekday(year, 1, _WEEKDAY_MON, 3),  # MLK Day (3rd Mon Jan)
        _nth_weekday(year, 2, _WEEKDAY_MON, 3),  # Washington's Birthday
        _last_weekday(year, 5, _WEEKDAY_MON),  # Memorial Day
        _observed(date(year, 6, 19)),  # Juneteenth
        _observed(date(year, 7, 4)),  # Independence Day
        _nth_weekday(year, 9, _WEEKDAY_MON, 1),  # Labor Day
        _nth_weekday(year, 10, _WEEKDAY_MON, 2),  # Columbus Day
        _observed(date(year, 11, 11)),  # Veterans Day
        _nth_weekday(year, 11, _WEEKDAY_MON, 4) + timedelta(days=3),  # Thanksgiving (4th Thu)
        _observed(date(year, 12, 25)),  # Christmas Day
    ]
    return sorted(set(rules))


def _is_us_federal_holiday(d: date, cache: dict[int, set[date]]) -> bool:
    if d.year not in cache:
        cache[d.year] = set(us_federal_holidays(d.year))
    return d in cache[d.year]


def _is_business_day(d: date, holiday_cache: dict[int, set[date]]) -> bool:
    return d.weekday() < _WEEKDAY_SAT and not _is_us_federal_holiday(d, holiday_cache)


def _next_business_day(d: date, holiday_cache: dict[int, set[date]]) -> date:
    cur = d
    while not _is_business_day(cur, holiday_cache):
        cur += timedelta(days=1)
    return cur


def _prev_business_day(d: date, holiday_cache: dict[int, set[date]]) -> date:
    cur = d
    while not _is_business_day(cur, holiday_cache):
        cur -= timedelta(days=1)
    return cur


def _add_business_days(d: date, n: int, holiday_cache: dict[int, set[date]]) -> date:
    """Add ``n`` business days (n may be negative). Day ``d`` is the anchor; the
    first step moves OFF ``d`` regardless of whether ``d`` itself is a
    business day."""
    cur = d
    if n > 0:
        for _ in range(n):
            cur += timedelta(days=1)
            while not _is_business_day(cur, holiday_cache):
                cur += timedelta(days=1)
    elif n < 0:
        for _ in range(-n):
            cur -= timedelta(days=1)
            while not _is_business_day(cur, holiday_cache):
                cur -= timedelta(days=1)
    return cur


# -- Release-day rules --------------------------------------------------------


def _eia_release_for_week_of(d: date, holiday_cache: dict[int, set[date]]) -> date:
    """The EIA WPSR scheduled release date for the ISO week containing ``d``.

    Base: Wednesday of that ISO week. Holiday rule: ``shift_next_business_day``
    (per ``v2/pit_store/calendars/eia_wpsr.yaml``).
    """
    monday = d - timedelta(days=d.weekday())
    wednesday = monday + timedelta(days=2)
    return _next_business_day(wednesday, holiday_cache)


def _cot_release_for_week_of(d: date, holiday_cache: dict[int, set[date]]) -> date:
    """CFTC COT scheduled release date for the ISO week containing ``d``.

    Base: Friday of that ISO week. Holiday rule: ``shift_prior_business_day``
    (per ``v2/pit_store/calendars/cftc_cot.yaml``).
    """
    monday = d - timedelta(days=d.weekday())
    friday = monday + timedelta(days=4)
    return _prev_business_day(friday, holiday_cache)


# -- CL expiry rule -----------------------------------------------------------


def cl_last_trade_date(contract_month: date) -> date:
    """Return the CL last-trade-date for the given contract month.

    CME rule (Light Sweet Crude Oil, CL):
        Trading terminates the 3rd business day before the 25th calendar
        day of the month *preceding* the contract month. If the 25th is a
        non-business day, count back from the prior business day instead
        of the 25th itself.

    ``contract_month`` accepts any date in the contract month; only its
    year/month components are read.
    """
    cm_year = contract_month.year
    cm_month = contract_month.month
    if cm_month == 1:
        prior_year = cm_year - 1
        prior_month = 12
    else:
        prior_year = cm_year
        prior_month = cm_month - 1
    anchor = date(prior_year, prior_month, 25)
    holiday_cache: dict[int, set[date]] = {}
    if not _is_business_day(anchor, holiday_cache):
        anchor = _prev_business_day(anchor, holiday_cache)
    return _add_business_days(anchor, -3, holiday_cache)


def _cl_last_trade_dates_in_range(
    start: date, end: date, holiday_cache: dict[int, set[date]]
) -> list[date]:
    """All CL last-trade-dates whose date falls in [start - 60d, end + 60d].

    The ±60d padding ensures that windows touching the boundary are
    detected; the function returns every distinct LTD whose contract
    month is anywhere from a few months before ``start`` to a few months
    after ``end``.
    """
    ltds: list[date] = []
    # Walk contract months from (start month - 2) to (end month + 2).
    cm_year, cm_month = start.year, start.month
    end_year, end_month = end.year, end.month
    # Step back 2 months to capture LTDs that straddle the start.
    for _ in range(2):
        if cm_month == 1:
            cm_year -= 1
            cm_month = 12
        else:
            cm_month -= 1
    # Iterate months until 2 past end.
    last_year, last_month = end_year, end_month
    for _ in range(3):
        if last_month == 12:
            last_year += 1
            last_month = 1
        else:
            last_month += 1
    while (cm_year, cm_month) <= (last_year, last_month):
        ltd = cl_last_trade_date(date(cm_year, cm_month, 1))
        ltds.append(ltd)
        if cm_month == 12:
            cm_year += 1
            cm_month = 1
        else:
            cm_month += 1
    # Sort and deduplicate (defensively).
    return sorted(set(ltds))


# -- Main builder -------------------------------------------------------------


def build_event_calendar(start: date, end: date) -> pd.DataFrame:
    """Build the deterministic event-flag DataFrame.

    Parameters
    ----------
    start, end : date
        Inclusive bounds. ``start <= end`` is required.

    Returns
    -------
    pd.DataFrame
        Indexed by ``DatetimeIndex`` named ``"date"``, daily, tz-naive.
        Columns: ``is_eia_release_day``, ``days_since_eia_release``,
        ``is_cot_release_day``, ``days_since_cot_release``,
        ``is_cl_expiry_window``, ``days_to_cl_last_trade_date``,
        ``is_roll_freeze_window``, ``is_us_holiday``.
    """
    if start > end:
        raise ValueError(f"start ({start}) must be <= end ({end})")

    holiday_cache: dict[int, set[date]] = {}

    # Pre-pad start by ~10 days so that "days_since_release" can look back.
    pad_start = start - timedelta(days=10)
    pad_end = end + timedelta(days=10)
    days = pd.date_range(pad_start, pad_end, freq="D").date

    # Compute scheduled release dates per ISO week for both calendars.
    eia_releases: set[date] = set()
    cot_releases: set[date] = set()
    for d in days:
        eia_releases.add(_eia_release_for_week_of(d, holiday_cache))
        cot_releases.add(_cot_release_for_week_of(d, holiday_cache))

    # CL last-trade-date table.
    ltds = _cl_last_trade_dates_in_range(pad_start, pad_end, holiday_cache)

    # Roll freeze: 5 business days BEFORE LTD (exclusive of LTD itself).
    # Expiry window: 3 business days BEFORE LTD (exclusive of LTD itself).
    expiry_window: set[date] = set()
    roll_freeze_window: set[date] = set()
    for ltd in ltds:
        # Walk back 1..5 business days from LTD.
        cur = ltd
        for k in range(1, 6):
            cur = _add_business_days(ltd, -k, holiday_cache)
            roll_freeze_window.add(cur)
            if k <= 3:
                expiry_window.add(cur)

    rows: list[dict[str, object]] = []
    for d in days:
        is_eia = d in eia_releases
        is_cot = d in cot_releases
        # days_since_eia_release: walk back to most recent eia release date.
        ds_eia = _days_since(d, eia_releases)
        ds_cot = _days_since(d, cot_releases)
        # days_to_cl_last_trade_date: signed; pick the nearest LTD.
        if ltds:
            nearest = min(ltds, key=lambda x: abs((x - d).days))
            d_ltd = (nearest - d).days
        else:
            d_ltd = 0
        rows.append(
            {
                "date": pd.Timestamp(d),
                "is_eia_release_day": is_eia,
                "days_since_eia_release": ds_eia,
                "is_cot_release_day": is_cot,
                "days_since_cot_release": ds_cot,
                "is_cl_expiry_window": d in expiry_window,
                "days_to_cl_last_trade_date": int(d_ltd),
                "is_roll_freeze_window": d in roll_freeze_window,
                "is_us_holiday": _is_us_federal_holiday(d, holiday_cache),
            }
        )
    df = pd.DataFrame(rows).set_index("date")
    df.index = pd.DatetimeIndex(df.index, name="date")
    # Trim to the requested [start, end] window.
    mask = (df.index >= pd.Timestamp(start)) & (df.index <= pd.Timestamp(end))
    return df.loc[mask].copy()


def _days_since(d: date, releases: set[date]) -> int:
    """Days since the most recent release on or before ``d``. If none, return
    a large sentinel (length of one year) — callers treat as "no recent release"."""
    cur = d
    for _ in range(400):
        if cur in releases:
            return (d - cur).days
        cur -= timedelta(days=1)
    return 400
