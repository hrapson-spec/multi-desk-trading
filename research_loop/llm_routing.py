"""LLM routing postcondition gate (spec §6.4).

Every LLM output flowing through the research loop passes through
commit_gate. The rule (directly from the spec):

    Tasks execute on the local tier by default. Any LLM output that
    contains any of the following artefacts MUST have been produced by
    an API-tier call; otherwise the artefact is rejected:
      - A draft or edit to any desk spec (desks/*/spec.md).
      - A new hypothesis proposal scheduled onto the experiment backlog.
      - A cross-desk synthesis artefact (any output citing two or more
        desks' Forecasts).

The gate is a **postcondition** (enforced on the artefact class, not on
task origin) because a task may start local, escalate mid-run, and
produce a spec edit at the end — what matters is the class of the
final artefact, not the starting tier.

Detection of cross_desk_synthesis: if citations list has ≥ 2 desks,
the artefact is auto-classified as cross_desk_synthesis regardless of
the caller's stated artefact_class. This prevents trivial
mis-classification from bypassing the rule.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts.v1 import LLMArtefact

API_ONLY_CLASSES: frozenset[str] = frozenset(
    {
        "spec_edit",
        "hypothesis_proposal",
        "cross_desk_synthesis",
    }
)


@dataclass(frozen=True)
class RoutingResult:
    """Outcome of the §6.4 commit gate."""

    passed: bool
    """True ⇒ artefact is permitted to commit. False ⇒ rejected; caller
    should either re-run on the API tier or log a capability debit."""

    effective_class: str
    """The artefact class the gate decided on (may differ from
    artefact.artefact_class if citations triggered the cross-desk
    synthesis override)."""

    reason: str
    """Human-readable explanation. For rejections, cites the rule that
    fired; for approvals, names the class that was checked."""


def _effective_class(artefact: LLMArtefact) -> str:
    """Decide the artefact class after applying the citations override.

    If the caller labelled the artefact as non-cross-desk-synthesis but
    the citations list has ≥ 2 desks, re-classify as
    cross_desk_synthesis. The override only strengthens the gate (never
    weakens it), so a caller-labelled cross_desk_synthesis stays as-is
    even if citations are empty.
    """
    if artefact.artefact_class != "cross_desk_synthesis" and len(set(artefact.citations)) >= 2:
        return "cross_desk_synthesis"
    return artefact.artefact_class


def commit_gate(artefact: LLMArtefact) -> RoutingResult:
    """Enforce the §6.4 postcondition.

    Returns a RoutingResult; callers inspect `.passed` to decide whether
    to commit the artefact or reject/escalate.
    """
    effective = _effective_class(artefact)

    if effective in API_ONLY_CLASSES and artefact.tier_of_origin != "api":
        return RoutingResult(
            passed=False,
            effective_class=effective,
            reason=(
                f"§6.4: artefact class {effective!r} requires API-tier origin; "
                f"got tier_of_origin={artefact.tier_of_origin!r} "
                f"(model={artefact.model_name!r})"
            ),
        )

    return RoutingResult(
        passed=True,
        effective_class=effective,
        reason=f"§6.4: class {effective!r} permitted from tier {artefact.tier_of_origin!r}",
    )
