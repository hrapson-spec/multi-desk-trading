"""Shared test fixtures.

Fixtures provide:
  tmp_db        — fresh DuckDB at a tmp path with schema initialised
  bus_dev       — Bus in development mode over tmp_db
  bus_prod      — Bus in production mode over tmp_db
  synth_clock   — deterministic clock for timestamps in tests
  stub_desk     — factory for stub desks emitting valid Forecasts
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bus import Bus
from contracts.target_variables import WTI_FRONT_MONTH_CLOSE
from contracts.v1 import (
    ClockHorizon,
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Print,
    Provenance,
    UncertaintyInterval,
)
from persistence import connect, init_db

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "main.duckdb"


@pytest.fixture()
def tmp_db(tmp_db_path: Path):
    conn = connect(tmp_db_path)
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture()
def bus_dev(tmp_db) -> Bus:
    return Bus(tmp_db, mode="development")


@pytest.fixture()
def bus_prod(tmp_db) -> Bus:
    return Bus(tmp_db, mode="production")


# ---------------------------------------------------------------------------
# Clock + synthesis fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def synth_clock() -> datetime:
    """Anchor timestamp used as 'now' across tests. Post-Kronos-cutoff and
    naturally-aligned with a Wednesday to exercise EIA WPSR timing."""
    return datetime(2026, 1, 7, 15, 0, 0, tzinfo=UTC)


@pytest.fixture()
def make_provenance() -> Callable[..., Provenance]:
    def _make(
        desk_name: str = "stub_desk",
        model_name: str = "stub_model",
        model_version: str = "0.0.0",
        code_commit: str = "0" * 40,
    ) -> Provenance:
        return Provenance(
            desk_name=desk_name,
            model_name=model_name,
            model_version=model_version,
            input_snapshot_hash="0" * 64,
            spec_hash="0" * 64,
            code_commit=code_commit,
        )

    return _make


@pytest.fixture()
def stub_forecast_factory(
    synth_clock: datetime, make_provenance: Callable[..., Provenance]
) -> Callable[..., Forecast]:
    """Factory producing valid-but-uninformative Forecasts (§4.5 stub discipline)."""

    def _make(
        *,
        target: str = WTI_FRONT_MONTH_CLOSE,
        horizon_days: int = 7,
        use_event_horizon: bool = False,
        event_id: str = "eia_wpsr",
        point_estimate: float = 0.0,
        lo: float = -1e9,
        hi: float = 1e9,
        sign: str = "none",
        staleness: bool = True,
        code_commit: str = "0" * 40,
        desk_name: str = "stub_desk",
    ) -> Forecast:
        horizon = (
            EventHorizon(
                event_id=event_id, expected_ts_utc=synth_clock + timedelta(days=horizon_days)
            )
            if use_event_horizon
            else ClockHorizon(duration=timedelta(days=horizon_days))
        )
        return Forecast(
            forecast_id=str(uuid.uuid4()),
            emission_ts_utc=synth_clock,
            target_variable=target,
            horizon=horizon,
            point_estimate=point_estimate,
            uncertainty=UncertaintyInterval(level=0.8, lower=lo, upper=hi),
            directional_claim=DirectionalClaim(variable=target, sign=sign),  # type: ignore[arg-type]
            staleness=staleness,
            confidence=0.5,
            provenance=make_provenance(desk_name=desk_name, code_commit=code_commit),
        )

    return _make


@pytest.fixture()
def stub_print_factory(synth_clock: datetime) -> Callable[..., Print]:
    def _make(
        *,
        target: str = WTI_FRONT_MONTH_CLOSE,
        value: float = 0.0,
        days_later: int = 7,
        event_id: str | None = "eia_wpsr",
    ) -> Print:
        return Print(
            print_id=str(uuid.uuid4()),
            realised_ts_utc=synth_clock + timedelta(days=days_later),
            target_variable=target,
            value=value,
            event_id=event_id,
        )

    return _make
