"""Research loop: event-driven + periodic paths (spec §6).

The research loop is the ONLY adaptation path. Controller weights,
desk specs, and experiment backlogs mutate via research-loop artefacts
that pass the human-gated promotion events (§11) or the staged-
candidate auto-promotion path (§8.3).

v0.2+ ships:
  - Dispatcher: priority-ordered processing of ResearchLoopEvents with
    a pluggable handler registry.
  - Handlers: gate_failure (v0.2 auto-retire), regime_transition
    (v0.2 Shapley refresh), data_ingestion_failure (v0.2 incident
    registry), feed_reliability_review (v0.2 rolling-rate rules),
    periodic_weekly (Shapley rollup).

v0.3 staged: LLM routing postcondition, grading-space attribution,
weight-promotion margin validation.
"""

from __future__ import annotations

from .dispatcher import Dispatcher, HandlerFn, HandlerResult
from .feed_latency_monitor import (
    PAGE_HINKLEY_DELTA,
    PAGE_HINKLEY_THRESHOLD,
    PageHinkleyState,
    initial_state,
    load_or_initial,
    observe_latency,
    persist,
    reset_for_feed,
    update_page_hinkley,
)
from .feed_reliability import (
    FeedReliabilityStats,
    active_target_variables_for_desk,
    compute_feed_failure_rate,
    count_recent_auto_retirements,
    feeds_eligible_for_reinstatement,
    feeds_meeting_retirement_criteria,
    historical_shapley_share,
    latest_nonzero_weight_for_desk,
    retired_desks_for_feed,
)
from .handlers import (
    FEED_RELIABILITY_HANDLER_V02,
    REGIME_TRANSITION_ARTEFACT_V03,
    data_ingestion_failure_handler,
    feed_reliability_review_handler,
    gate_failure_handler,
    periodic_weekly_handler,
    regime_transition_handler,
)
from .kpi import LatencyReport, PerTypeLatency, compute_latency_report
from .llm_routing import API_ONLY_CLASSES, RoutingResult, commit_gate
from .promotion import (
    PROMOTION_ARTEFACT_SHAPLEY_V02,
    PROMOTION_ARTEFACT_VALIDATED_V03,
    ValidationResult,
    promote_weights,
    propose_and_promote_from_shapley,
    propose_validate_and_promote,
    propose_weights_from_shapley,
    validate_candidate_vs_current,
)
from .remediation import (
    FEED_UNRELIABLE_PREFIX,
    HARMFUL_FAILURE_PREFIX,
    REINSTATE_PREFIX,
    RETIRE_ARTEFACT_PREFIX,
    is_harmful,
    reinstate_desk_direct,
    retire_desk_for_all_regimes,
    retire_desk_for_regime,
)

__all__ = [
    "API_ONLY_CLASSES",
    "Dispatcher",
    "FEED_RELIABILITY_HANDLER_V02",
    "FEED_UNRELIABLE_PREFIX",
    "FeedReliabilityStats",
    "HARMFUL_FAILURE_PREFIX",
    "HandlerFn",
    "HandlerResult",
    "LatencyReport",
    "PAGE_HINKLEY_DELTA",
    "PAGE_HINKLEY_THRESHOLD",
    "PROMOTION_ARTEFACT_SHAPLEY_V02",
    "PROMOTION_ARTEFACT_VALIDATED_V03",
    "PageHinkleyState",
    "PerTypeLatency",
    "REGIME_TRANSITION_ARTEFACT_V03",
    "REINSTATE_PREFIX",
    "RETIRE_ARTEFACT_PREFIX",
    "RoutingResult",
    "ValidationResult",
    "active_target_variables_for_desk",
    "commit_gate",
    "compute_feed_failure_rate",
    "compute_latency_report",
    "count_recent_auto_retirements",
    "data_ingestion_failure_handler",
    "feed_reliability_review_handler",
    "feeds_eligible_for_reinstatement",
    "feeds_meeting_retirement_criteria",
    "gate_failure_handler",
    "historical_shapley_share",
    "latest_nonzero_weight_for_desk",
    "initial_state",
    "is_harmful",
    "load_or_initial",
    "observe_latency",
    "periodic_weekly_handler",
    "persist",
    "promote_weights",
    "propose_and_promote_from_shapley",
    "propose_validate_and_promote",
    "propose_weights_from_shapley",
    "regime_transition_handler",
    "reinstate_desk_direct",
    "reset_for_feed",
    "retire_desk_for_all_regimes",
    "retire_desk_for_regime",
    "retired_desks_for_feed",
    "update_page_hinkley",
    "validate_candidate_vs_current",
]
