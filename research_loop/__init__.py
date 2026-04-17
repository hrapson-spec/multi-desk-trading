"""Research loop: event-driven + periodic paths (spec §6).

The research loop is the ONLY adaptation path. Controller weights,
desk specs, and experiment backlogs mutate via research-loop artefacts
that pass the human-gated promotion events (§11) or the staged-
candidate auto-promotion path (§8.3).

Phase 1 v0.1 ships:
  - Dispatcher: priority-ordered processing of ResearchLoopEvents with
    a pluggable handler registry.
  - periodic_weekly_handler: reads the week's Decisions, runs a
    Shapley rollup, stores a compact summary in the event's
    produced_artefact field.

LLM routing (§6.4) postcondition gate, data-ingestion-failure RCA,
weight-promotion candidate proposals, and the §6.5 trading-path-
forbidden invariant are staged for v0.2+.
"""

from __future__ import annotations

from .dispatcher import Dispatcher, HandlerFn, HandlerResult
from .handlers import (
    data_ingestion_failure_handler,
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

__all__ = [
    "API_ONLY_CLASSES",
    "Dispatcher",
    "HandlerFn",
    "HandlerResult",
    "LatencyReport",
    "PROMOTION_ARTEFACT_SHAPLEY_V02",
    "PROMOTION_ARTEFACT_VALIDATED_V03",
    "PerTypeLatency",
    "RoutingResult",
    "ValidationResult",
    "commit_gate",
    "compute_latency_report",
    "data_ingestion_failure_handler",
    "gate_failure_handler",
    "periodic_weekly_handler",
    "regime_transition_handler",
    "promote_weights",
    "propose_and_promote_from_shapley",
    "propose_validate_and_promote",
    "propose_weights_from_shapley",
    "validate_candidate_vs_current",
]
