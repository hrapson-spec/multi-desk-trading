"""Degradation ladder — pure state-machine transition.

Per v2_decision_contract §4:

    State         | Trigger                                    | Effect
    --------------+--------------------------------------------+---------------------
    HEALTHY       | fresh valid decision; within TTL           | rebalance to b_t
    SOFT_ABSTAIN  | abstain for n ≤ n_soft ticks; within TTL   | hold last target
    AGED          | n > n_soft OR TTL breached                 | decay target × (1-λ)
    HARD_FAIL     | kill-switch halting or critical failure    | force target = 0

The kill-switch check is ABOVE the ladder (docs/v2/kill_switch_and_rollback.md §7):
    kill_switch.state != enabled → HARD_FAIL regardless of forecast state.

This module is pure; persistence and the rebalance decision live in the
simulator (B6b). `step` returns only the new `ExposureState`.
"""

from __future__ import annotations

from dataclasses import dataclass

from v2.contracts.decision_v2 import DegradationState


@dataclass(frozen=True)
class ExposureState:
    state: DegradationState
    current_target: float  # effective target exposure (fraction of sleeve)
    last_valid_target: float  # last target from a HEALTHY decision
    ticks_since_valid: int  # how many abstain ticks since the last HEALTHY

    def __post_init__(self) -> None:
        if not (-1.0 <= self.current_target <= 1.0):
            raise ValueError(f"current_target must be in [-1, 1], got {self.current_target}")
        if not (-1.0 <= self.last_valid_target <= 1.0):
            raise ValueError(f"last_valid_target must be in [-1, 1], got {self.last_valid_target}")
        if self.ticks_since_valid < 0:
            raise ValueError("ticks_since_valid must be >= 0")


@dataclass(frozen=True)
class TickEvent:
    family_abstained: bool
    b_t: float | None  # must be None iff family_abstained
    ttl_breached: bool
    kill_switch_halting: bool

    def __post_init__(self) -> None:
        if self.family_abstained and self.b_t is not None:
            raise ValueError("b_t must be None when family_abstained=True")
        if (not self.family_abstained) and self.b_t is None:
            raise ValueError("b_t is required when family_abstained=False")
        if self.b_t is not None and not (-1.0 <= self.b_t <= 1.0):
            raise ValueError(f"b_t must be in [-1, 1], got {self.b_t}")


def step(
    state: ExposureState,
    event: TickEvent,
    *,
    n_soft: int,
    decay_lambda: float,
) -> ExposureState:
    """Advance the exposure state by one decision tick.

    Precedence:
        1. kill_switch_halting   → HARD_FAIL, target = 0
        2. family not abstaining → HEALTHY, target = b_t, counter reset
        3. ttl_breached          → HARD_FAIL, target = 0
        4. ticks_since_valid + 1 ≤ n_soft → SOFT_ABSTAIN, hold last target
        5. otherwise             → AGED, target × (1 - λ)
    """
    if n_soft < 0:
        raise ValueError("n_soft must be >= 0")
    if not (0.0 <= decay_lambda <= 1.0):
        raise ValueError("decay_lambda must be in [0, 1]")

    # Rule 1: kill-switch is always highest priority.
    if event.kill_switch_halting:
        return ExposureState(
            state=DegradationState.HARD_FAIL,
            current_target=0.0,
            last_valid_target=state.last_valid_target,
            ticks_since_valid=state.ticks_since_valid + 1,
        )

    # Rule 2: a fresh valid decision resets everything.
    if not event.family_abstained:
        assert event.b_t is not None
        return ExposureState(
            state=DegradationState.HEALTHY,
            current_target=event.b_t,
            last_valid_target=event.b_t,
            ticks_since_valid=0,
        )

    # Rule 3: TTL breached overrides soft-abstain.
    if event.ttl_breached:
        return ExposureState(
            state=DegradationState.HARD_FAIL,
            current_target=0.0,
            last_valid_target=state.last_valid_target,
            ticks_since_valid=state.ticks_since_valid + 1,
        )

    next_ticks = state.ticks_since_valid + 1

    # Rule 4: within soft-abstain window, hold the last valid target.
    if next_ticks <= n_soft:
        return ExposureState(
            state=DegradationState.SOFT_ABSTAIN,
            current_target=state.last_valid_target,
            last_valid_target=state.last_valid_target,
            ticks_since_valid=next_ticks,
        )

    # Rule 5: aged → decay toward zero.
    decayed = state.current_target * (1.0 - decay_lambda)
    if abs(decayed) < 1e-12:
        decayed = 0.0
    return ExposureState(
        state=DegradationState.AGED,
        current_target=decayed,
        last_valid_target=state.last_valid_target,
        ticks_since_valid=next_ticks,
    )
