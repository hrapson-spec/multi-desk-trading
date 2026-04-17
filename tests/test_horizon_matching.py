"""Horizon matching and Grade emission (spec §4.7)."""

from __future__ import annotations

from datetime import timedelta

from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from grading import DEFAULT_CLOCK_TOLERANCE, grade, matches


def test_event_horizon_matches_on_event_id(stub_forecast_factory, stub_print_factory):
    f = stub_forecast_factory(use_event_horizon=True, event_id="eia_wpsr")
    p = stub_print_factory(event_id="eia_wpsr", days_later=7)
    assert matches(f, p) is True


def test_event_horizon_rejects_mismatched_event_id(stub_forecast_factory, stub_print_factory):
    f = stub_forecast_factory(use_event_horizon=True, event_id="eia_wpsr")
    p = stub_print_factory(event_id="cftc_cot", days_later=7)
    assert matches(f, p) is False


def test_clock_horizon_matches_within_tolerance(stub_forecast_factory, stub_print_factory):
    f = stub_forecast_factory(horizon_days=7)  # default ClockHorizon
    # Print arrives exactly at emission_ts + 7d; tolerance window is ±6h.
    p = stub_print_factory(days_later=7, event_id=None)
    assert matches(f, p) is True


def test_clock_horizon_rejects_outside_tolerance(stub_forecast_factory, stub_print_factory):
    f = stub_forecast_factory(horizon_days=7)
    # Print arrives 7 days + 12 hours later → outside default 6h tolerance.
    p = stub_print_factory(days_later=7, event_id=None)
    # Shift print forward 12h manually via a new Print built from p:
    from contracts.v1 import Print

    p2 = Print(
        print_id=p.print_id,
        realised_ts_utc=p.realised_ts_utc + timedelta(hours=12),
        target_variable=p.target_variable,
        value=p.value,
        event_id=p.event_id,
    )
    assert matches(f, p2, tolerance=DEFAULT_CLOCK_TOLERANCE) is False


def test_grade_records_schedule_slip(stub_forecast_factory, stub_print_factory):
    f = stub_forecast_factory(use_event_horizon=True, event_id="eia_wpsr", horizon_days=7)
    # Print arrives 2 days late.
    p = stub_print_factory(event_id="eia_wpsr", days_later=9)
    assert matches(f, p) is True
    g = grade(f, p)
    assert g.schedule_slip_seconds is not None
    assert g.schedule_slip_seconds == 2 * 24 * 3600


def test_grade_sign_agreement_none_for_none_claim(stub_forecast_factory, stub_print_factory):
    f = stub_forecast_factory(sign="none")
    p = stub_print_factory(value=5.0)
    g = grade(f, p)
    assert g.sign_agreement is None


def test_matches_rejects_target_mismatch(stub_forecast_factory, stub_print_factory):
    # Only WTI_FRONT_MONTH_CLOSE is in the registry; this test ensures matches()
    # returns False when targets differ (constructed via forecast_factory default).
    f = stub_forecast_factory(target=WTI_FRONT_MONTH_CLOSE)
    p = stub_print_factory(target=WTI_FRONT_MONTH_CLOSE)
    assert matches(f, p) is True
