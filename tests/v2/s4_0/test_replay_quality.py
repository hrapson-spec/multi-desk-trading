"""Replay quality policy tests for S4-0 fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from v2.s4_0.replay_quality import ReplayTick, analyze_tick_quality


def _ts(minute: int) -> datetime:
    return datetime(2026, 4, 24, 13, minute, tzinfo=UTC)


def test_same_timestamp_multiple_events_are_reported_without_reordering():
    ticks = [
        ReplayTick("CLM6", _ts(0), _ts(0), 1, exchange_sequence_number=10),
        ReplayTick("CLM6", _ts(0), _ts(0), 2, exchange_sequence_number=11),
    ]

    report = analyze_tick_quality(ticks)

    assert report.same_timestamp_groups == 1
    assert report.out_of_order_rows == 0
    assert report.sequence_gap_count == 0


def test_sequence_gap_is_material_sev1():
    ticks = [
        ReplayTick("CLM6", _ts(0), _ts(0), 1, exchange_sequence_number=1),
        ReplayTick("CLM6", _ts(1), _ts(1), 2, exchange_sequence_number=3),
    ]

    report = analyze_tick_quality(ticks)

    assert report.sequence_gap_count == 1
    assert report.has_material_gap is True
    assert report.findings[0].kind == "sequence_gap"
    assert report.findings[0].severity == "SEV1"


def test_time_gap_without_sequence_break_is_not_the_same_as_sequence_gap():
    ticks = [
        ReplayTick("CLM6", _ts(0), _ts(0), 1, exchange_sequence_number=1),
        ReplayTick("CLM6", _ts(30), _ts(30), 2, exchange_sequence_number=2),
    ]

    report = analyze_tick_quality(
        ticks,
        max_time_gap_without_sequence_break=timedelta(minutes=10),
    )

    assert report.sequence_gap_count == 0
    assert report.findings[0].kind == "time_gap_without_expected_sequence_break"
    assert report.findings[0].severity == "SEV2"


def test_expected_symbol_without_ticks_is_missing_segment():
    ticks = [ReplayTick("CLM6", _ts(0), _ts(0), 1, exchange_sequence_number=1)]

    report = analyze_tick_quality(ticks, expected_symbols={"CLM6", "CLN6"})

    assert report.has_material_gap is True
    assert report.findings[0].kind == "missing_contract_segment"
    assert report.findings[0].symbol == "CLN6"


def test_global_sequence_scope_does_not_create_per_symbol_false_gap():
    ticks = [
        ReplayTick("CLM6", _ts(0), _ts(0), 1, exchange_sequence_number=1),
        ReplayTick("CLN6", _ts(1), _ts(1), 2, exchange_sequence_number=2),
        ReplayTick("CLM6", _ts(2), _ts(2), 3, exchange_sequence_number=3),
    ]

    per_symbol = analyze_tick_quality(ticks, sequence_scope="per_symbol")
    global_scope = analyze_tick_quality(ticks, sequence_scope="global")

    assert per_symbol.sequence_gap_count == 1
    assert global_scope.sequence_gap_count == 0
