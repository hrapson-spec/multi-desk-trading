"""Release-calendar YAML loader tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import yaml
from pydantic import ValidationError

from v2.pit_store.release_calendar import (
    ReleaseCalendar,
    load_calendar,
    load_calendars_dir,
)

_VALID = {
    "source": "eia_wpsr",
    "description": "EIA Weekly Petroleum Status Report",
    "publisher": "U.S. EIA",
    "calendar_version": "1.0.0",
    "release_cadence": {
        "type": "weekly",
        "weekday": "wednesday",
        "earliest_release_time_et": "10:30",
        "holiday_rule": "shift_next_business_day",
    },
    "observation_semantics": {
        "reporting_period": "week_ending_friday_prior",
        "lag_to_publication_days": 5,
    },
    "revision_policy": "ad_hoc",
    "pit_eligibility_rule": "release_ts <= as_of_ts",
    "source_confidence": {
        "baseline": 0.95,
        "degradation_conditions": ["federal_shutdown"],
    },
    "data_quality_multipliers": {
        "fresh": 1.0,
        "stale_1week": 0.85,
        "stale_2week": 0.60,
        "stale_over_2week": 0.0,
    },
}


def _write_yaml(path, data):
    path.write_text(yaml.safe_dump(data))


def test_load_calendar_valid(tmp_path):
    p = tmp_path / "eia_wpsr.yaml"
    _write_yaml(p, _VALID)
    cal = load_calendar(p)
    assert isinstance(cal, ReleaseCalendar)
    assert cal.source == "eia_wpsr"
    assert cal.release_cadence.weekday == "wednesday"
    assert cal.source_confidence.baseline == 0.95


def test_load_calendar_invalid_time_format(tmp_path):
    p = tmp_path / "bad.yaml"
    bad = {
        **_VALID,
        "release_cadence": {**_VALID["release_cadence"], "earliest_release_time_et": "10:3"},
    }
    _write_yaml(p, bad)
    with pytest.raises(ValidationError):
        load_calendar(p)


def test_load_calendar_confidence_out_of_range(tmp_path):
    p = tmp_path / "bad.yaml"
    bad = {**_VALID, "source_confidence": {**_VALID["source_confidence"], "baseline": 1.5}}
    _write_yaml(p, bad)
    with pytest.raises(ValidationError):
        load_calendar(p)


def test_load_calendars_dir_duplicate_source_rejected(tmp_path):
    _write_yaml(tmp_path / "a.yaml", _VALID)
    _write_yaml(tmp_path / "b.yaml", _VALID)
    with pytest.raises(ValueError):
        load_calendars_dir(tmp_path)


def test_is_eligible_simple():
    cal = ReleaseCalendar.model_validate(_VALID)
    release_ts = datetime(2026, 1, 14, 15, 30, tzinfo=UTC)
    assert cal.is_eligible(release_ts, datetime(2026, 1, 14, 15, 30, tzinfo=UTC)) is True
    assert cal.is_eligible(release_ts, datetime(2026, 1, 14, 15, 29, tzinfo=UTC)) is False


def test_latency_guard_minutes_delays_eligibility():
    cal = ReleaseCalendar.model_validate({**_VALID, "latency_guard_minutes": 5})
    release_ts = datetime(2026, 1, 14, 15, 30, tzinfo=UTC)
    assert cal.usable_after_ts(release_ts) == release_ts + timedelta(minutes=5)
    assert cal.is_eligible(release_ts, release_ts + timedelta(minutes=4, seconds=59)) is False
    assert cal.is_eligible(release_ts, release_ts + timedelta(minutes=5)) is True


def test_release_timezone_dst_uses_america_new_york():
    cal = ReleaseCalendar.model_validate(_VALID)
    winter = cal.release_datetime_utc(date(2026, 1, 14))
    summer = cal.release_datetime_utc(date(2026, 7, 15))
    assert winter == datetime(2026, 1, 14, 15, 30, tzinfo=UTC)
    assert summer == datetime(2026, 7, 15, 14, 30, tzinfo=UTC)


def test_quality_multiplier_for_lag():
    cal = ReleaseCalendar.model_validate(_VALID)
    assert cal.quality_multiplier_for_lag(0) == 1.0
    assert cal.quality_multiplier_for_lag(3) == 1.0
    assert cal.quality_multiplier_for_lag(8) == 0.85
    assert cal.quality_multiplier_for_lag(15) == 0.60
    assert cal.quality_multiplier_for_lag(30) == 0.0
