"""RealisedOutcome contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from v2.eval import RealisedOutcome


def _kw(**overrides) -> dict:
    base: dict = {
        "target_variable": "WTI_FRONT_1W_LOG_RETURN",
        "decision_ts": datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
        "realisation_ts": datetime(2026, 4, 29, 21, 0, tzinfo=UTC),
        "horizon_days": 5,
        "realised_value": 0.012,
        "source": "wti_front_month",
    }
    base.update(overrides)
    return base


def test_valid():
    o = RealisedOutcome(**_kw())
    assert o.realised_value == 0.012


def test_naive_decision_ts_rejected():
    with pytest.raises(ValidationError):
        RealisedOutcome(**_kw(decision_ts=datetime(2026, 4, 22, 21, 0)))


def test_realisation_before_decision_rejected():
    with pytest.raises(ValidationError):
        RealisedOutcome(**_kw(realisation_ts=datetime(2026, 4, 20, 21, 0, tzinfo=UTC)))


def test_nonpositive_horizon_rejected():
    with pytest.raises(ValidationError):
        RealisedOutcome(**_kw(horizon_days=0))


def test_frozen():
    o = RealisedOutcome(**_kw())
    with pytest.raises(ValidationError):
        o.realised_value = 0.5  # type: ignore[misc]
