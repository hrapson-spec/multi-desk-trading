"""Tests for the §6.4 LLM routing postcondition gate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from contracts.v1 import LLMArtefact
from research_loop import API_ONLY_CLASSES, commit_gate

NOW = datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC)


def _artefact(
    *,
    cls: str,
    tier: str = "local",
    citations: list[str] | None = None,
    content: str = "stub content",
    model_name: str = "mistral-7b-q4",
) -> LLMArtefact:
    return LLMArtefact(
        artefact_id=str(uuid.uuid4()),
        produced_at_utc=NOW,
        tier_of_origin=tier,  # type: ignore[arg-type]
        artefact_class=cls,  # type: ignore[arg-type]
        content=content,
        model_name=model_name,
        citations=citations or [],
    )


# ---------------------------------------------------------------------------
# API-only classes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", list(API_ONLY_CLASSES))
def test_api_only_classes_reject_local_tier(cls):
    result = commit_gate(_artefact(cls=cls, tier="local"))
    assert not result.passed
    assert "§6.4" in result.reason
    assert cls in result.reason


@pytest.mark.parametrize("cls", list(API_ONLY_CLASSES))
def test_api_only_classes_accept_api_tier(cls):
    result = commit_gate(_artefact(cls=cls, tier="api", model_name="claude-opus-4-7"))
    assert result.passed
    assert result.effective_class == cls


# ---------------------------------------------------------------------------
# Permissive classes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cls", ["daily_log_summary", "attribution_query", "other"])
def test_permissive_classes_allow_local_tier(cls):
    result = commit_gate(_artefact(cls=cls, tier="local"))
    assert result.passed
    assert result.effective_class == cls


@pytest.mark.parametrize("cls", ["daily_log_summary", "attribution_query", "other"])
def test_permissive_classes_allow_api_tier(cls):
    result = commit_gate(_artefact(cls=cls, tier="api", model_name="claude-opus-4-7"))
    assert result.passed


# ---------------------------------------------------------------------------
# Cross-desk-synthesis citation override
# ---------------------------------------------------------------------------


def test_citations_override_reclassifies_as_cross_desk_synthesis():
    """A caller-stated class of 'other' with 2+ desk citations is
    re-classified as cross_desk_synthesis and then gated on API-tier."""
    a = _artefact(cls="other", tier="local", citations=["storage_curve", "macro"])
    result = commit_gate(a)
    assert not result.passed
    assert result.effective_class == "cross_desk_synthesis"
    assert "§6.4" in result.reason


def test_single_citation_does_not_trigger_override():
    a = _artefact(cls="other", tier="local", citations=["storage_curve"])
    result = commit_gate(a)
    assert result.passed
    assert result.effective_class == "other"


def test_citations_override_passes_when_api_tier():
    a = _artefact(
        cls="other",
        tier="api",
        model_name="claude-opus-4-7",
        citations=["storage_curve", "macro", "supply"],
    )
    result = commit_gate(a)
    assert result.passed
    assert result.effective_class == "cross_desk_synthesis"


def test_duplicate_citations_count_as_one():
    """Citations are deduplicated before the 2+ check — a local-tier
    artefact that cites storage_curve twice should NOT trigger the
    override on the strength of that alone."""
    a = _artefact(cls="other", tier="local", citations=["storage_curve", "storage_curve"])
    result = commit_gate(a)
    assert result.passed
    assert result.effective_class == "other"


# ---------------------------------------------------------------------------
# Bidirectional consistency: caller-labelled cross_desk_synthesis stays as-is
# even with empty citations list (override only strengthens, never weakens)
# ---------------------------------------------------------------------------


def test_caller_labelled_cross_desk_synthesis_still_gated_even_without_citations():
    a = _artefact(cls="cross_desk_synthesis", tier="local", citations=[])
    result = commit_gate(a)
    assert not result.passed
    assert result.effective_class == "cross_desk_synthesis"
