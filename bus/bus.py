"""Synchronous in-memory message bus with validation.

Every inter-component message flows through the bus. Validation rules
(spec §3.1, §3.4, §4.3–4.7):

1. Pydantic type validation (automatic on typed `publish_*` methods).
2. target_variable MUST be in contracts.target_variables.KNOWN_TARGETS.
3. provenance.code_commit MUST NOT end with "-dirty" when mode ∈
   {production, replay}.

On valid publish: persist to DuckDB → notify synchronous subscribers.
On invalid publish: raise BusValidationError; nothing is persisted;
nothing is dispatched.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Literal

import duckdb

from contracts.target_variables import is_known
from contracts.v1 import (
    AttributionLodo,
    AttributionShapley,
    ControllerParams,
    Decision,
    Forecast,
    Grade,
    Print,
    RegimeLabel,
    ResearchLoopEvent,
    SignalWeight,
)
from persistence import (
    insert_attribution_lodo,
    insert_attribution_shapley,
    insert_controller_params,
    insert_decision,
    insert_forecast,
    insert_grade,
    insert_print,
    insert_regime_label,
    insert_research_loop_event,
    insert_signal_weight,
)

BusMode = Literal["development", "production", "replay"]


class BusValidationError(ValueError):
    """Raised when the bus rejects a publish attempt.

    Carries a machine-readable `reason` for test assertions.
    """

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


class Bus:
    """Synchronous in-memory dispatcher. Single-threaded by design."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, mode: BusMode = "development") -> None:
        self._conn = conn
        self._mode = mode
        self._subscribers: dict[type, list[Callable[..., None]]] = defaultdict(list)

    @property
    def mode(self) -> BusMode:
        return self._mode

    # --- Subscription ----------------------------------------------------

    def subscribe(self, event_type: type, handler: Callable[..., None]) -> None:
        self._subscribers[event_type].append(handler)

    def _dispatch(self, event: object) -> None:
        for handler in self._subscribers.get(type(event), []):
            handler(event)

    # --- Internal validation helpers ------------------------------------

    def _check_dirty_tree(self, code_commit: str) -> None:
        if self._mode in ("production", "replay") and code_commit.endswith("-dirty"):
            raise BusValidationError(
                reason="dirty_tree_rejected",
                message=(
                    f"mode={self._mode!r} rejects provenance.code_commit "
                    f"ending in '-dirty' (got {code_commit!r})"
                ),
            )

    def _check_target_registry(self, target_variable: str) -> None:
        if not is_known(target_variable):
            raise BusValidationError(
                reason="unknown_target_variable",
                message=(
                    f"target_variable {target_variable!r} is not in "
                    f"contracts.target_variables.KNOWN_TARGETS"
                ),
            )

    # --- Publish methods -------------------------------------------------

    def publish_forecast(self, f: Forecast) -> None:
        # Pydantic model validation already ran at construction time.
        # Re-validate registry membership at the bus (belt + braces).
        self._check_target_registry(f.target_variable)
        self._check_dirty_tree(f.provenance.code_commit)
        insert_forecast(self._conn, f)
        self._dispatch(f)

    def publish_print(self, p: Print) -> None:
        self._check_target_registry(p.target_variable)
        insert_print(self._conn, p)
        self._dispatch(p)

    def publish_grade(self, g: Grade) -> None:
        insert_grade(self._conn, g)
        self._dispatch(g)

    def publish_decision(self, d: Decision) -> None:
        self._check_dirty_tree(d.provenance.code_commit)
        insert_decision(self._conn, d)
        self._dispatch(d)

    def publish_signal_weight(self, w: SignalWeight) -> None:
        # target_variable in SignalWeight is the weight's addressing key;
        # still must be a registered target.
        self._check_target_registry(w.target_variable)
        insert_signal_weight(self._conn, w)
        self._dispatch(w)

    def publish_controller_params(self, cp: ControllerParams) -> None:
        insert_controller_params(self._conn, cp)
        self._dispatch(cp)

    def publish_regime_label(self, r: RegimeLabel) -> None:
        self._check_dirty_tree(r.classifier_provenance.code_commit)
        insert_regime_label(self._conn, r)
        self._dispatch(r)

    def publish_research_event(self, e: ResearchLoopEvent) -> None:
        insert_research_loop_event(self._conn, e)
        self._dispatch(e)

    def publish_attribution_lodo(self, a: AttributionLodo) -> None:
        insert_attribution_lodo(self._conn, a)
        self._dispatch(a)

    def publish_attribution_shapley(self, a: AttributionShapley) -> None:
        insert_attribution_shapley(self._conn, a)
        self._dispatch(a)
