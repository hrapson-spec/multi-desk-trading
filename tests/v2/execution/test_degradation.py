"""Degradation ladder tests."""

from __future__ import annotations

import pytest

from v2.contracts.decision_v2 import DegradationState
from v2.execution import ExposureState, TickEvent, step


def _healthy(target: float = 0.4) -> ExposureState:
    return ExposureState(
        state=DegradationState.HEALTHY,
        current_target=target,
        last_valid_target=target,
        ticks_since_valid=0,
    )


def test_valid_decision_resets_state():
    prior = ExposureState(
        state=DegradationState.AGED,
        current_target=0.2,
        last_valid_target=0.5,
        ticks_since_valid=5,
    )
    new = step(
        prior,
        TickEvent(family_abstained=False, b_t=0.7, ttl_breached=False, kill_switch_halting=False),
        n_soft=3,
        decay_lambda=0.2,
    )
    assert new.state == DegradationState.HEALTHY
    assert new.current_target == 0.7
    assert new.last_valid_target == 0.7
    assert new.ticks_since_valid == 0


def test_first_abstain_enters_soft_abstain_holding_target():
    prior = _healthy(target=0.6)
    event = TickEvent(
        family_abstained=True, b_t=None, ttl_breached=False, kill_switch_halting=False
    )
    new = step(prior, event, n_soft=3, decay_lambda=0.2)
    assert new.state == DegradationState.SOFT_ABSTAIN
    assert new.current_target == 0.6
    assert new.last_valid_target == 0.6
    assert new.ticks_since_valid == 1


def test_soft_abstain_persists_up_to_n_soft():
    state = _healthy(target=0.5)
    for expected_tick in range(1, 4):
        state = step(
            state,
            TickEvent(
                family_abstained=True, b_t=None, ttl_breached=False, kill_switch_halting=False
            ),
            n_soft=3,
            decay_lambda=0.2,
        )
        assert state.state == DegradationState.SOFT_ABSTAIN
        assert state.ticks_since_valid == expected_tick
        assert state.current_target == 0.5


def test_aged_decays_target_after_n_soft():
    state = _healthy(target=0.5)
    # Walk through soft window (3 abstains), then one more → AGED.
    for _ in range(3):
        state = step(
            state,
            TickEvent(
                family_abstained=True, b_t=None, ttl_breached=False, kill_switch_halting=False
            ),
            n_soft=3,
            decay_lambda=0.2,
        )
    state = step(
        state,
        TickEvent(family_abstained=True, b_t=None, ttl_breached=False, kill_switch_halting=False),
        n_soft=3,
        decay_lambda=0.2,
    )
    assert state.state == DegradationState.AGED
    assert state.current_target == pytest.approx(0.5 * 0.8)


def test_aged_decays_on_each_subsequent_abstain():
    state = _healthy(target=1.0)
    for _ in range(4):
        state = step(
            state,
            TickEvent(
                family_abstained=True, b_t=None, ttl_breached=False, kill_switch_halting=False
            ),
            n_soft=3,
            decay_lambda=0.5,
        )
    assert state.state == DegradationState.AGED
    assert state.current_target == pytest.approx(0.5)
    # One more decay
    state = step(
        state,
        TickEvent(family_abstained=True, b_t=None, ttl_breached=False, kill_switch_halting=False),
        n_soft=3,
        decay_lambda=0.5,
    )
    assert state.current_target == pytest.approx(0.25)


def test_ttl_breach_forces_hard_fail():
    prior = _healthy(target=0.5)
    event = TickEvent(family_abstained=True, b_t=None, ttl_breached=True, kill_switch_halting=False)
    new = step(prior, event, n_soft=3, decay_lambda=0.2)
    assert new.state == DegradationState.HARD_FAIL
    assert new.current_target == 0.0


def test_kill_switch_overrides_everything():
    prior = _healthy(target=0.8)
    # Even with a valid b_t, kill_switch halting forces HARD_FAIL.
    event = TickEvent(family_abstained=False, b_t=0.9, ttl_breached=False, kill_switch_halting=True)
    new = step(prior, event, n_soft=3, decay_lambda=0.2)
    assert new.state == DegradationState.HARD_FAIL
    assert new.current_target == 0.0


def test_invalid_event_consistency_rejected():
    with pytest.raises(ValueError):
        TickEvent(family_abstained=True, b_t=0.5, ttl_breached=False, kill_switch_halting=False)
    with pytest.raises(ValueError):
        TickEvent(family_abstained=False, b_t=None, ttl_breached=False, kill_switch_halting=False)


def test_invalid_params_rejected():
    prior = _healthy()
    event = TickEvent(
        family_abstained=True, b_t=None, ttl_breached=False, kill_switch_halting=False
    )
    with pytest.raises(ValueError):
        step(prior, event, n_soft=-1, decay_lambda=0.2)
    with pytest.raises(ValueError):
        step(prior, event, n_soft=3, decay_lambda=1.5)
