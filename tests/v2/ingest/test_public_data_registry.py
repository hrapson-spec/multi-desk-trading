"""Foundation tests for the public-data registry (Phase B2b Wave 0)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from v2.ingest.public_data_registry import (
    RegistryEntry,
    eligible_for_model,
    entries_for_source,
    load_registry,
)


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def test_registry_loads(registry):
    assert len(registry.entries) > 0


def test_no_duplicate_keys(registry):
    keys = [e.key for e in registry.entries]
    assert len(keys) == len(set(keys)), "duplicate keys detected"


def test_every_entry_has_rights_and_eligibility(registry):
    for e in registry.entries:
        assert e.rights_status in {"public", "display_only", "manual_only", "restricted"}
        assert isinstance(e.model_eligible, bool)


def test_rights_gate_invariant_rejects_display_only_eligible():
    with pytest.raises(ValidationError):
        RegistryEntry(
            key="test_bad",
            source="test",
            description="bad: display_only must not be model_eligible",
            source_url="https://example.com/x",
            retrieval_method="api",
            rights_status="display_only",
            model_eligible=True,
            frequency="daily",
        )


def test_rights_gate_invariant_rejects_manual_only_eligible():
    with pytest.raises(ValidationError):
        RegistryEntry(
            key="test_bad2",
            source="test",
            description="bad: manual_only must not be model_eligible",
            source_url="https://example.com/x",
            retrieval_method="manual_event_feature",
            rights_status="manual_only",
            model_eligible=True,
            frequency="monthly",
        )


def test_rights_gate_allows_public_eligible():
    e = RegistryEntry(
        key="test_ok",
        source="test",
        description="public + eligible is fine",
        source_url="https://example.com/x",
        retrieval_method="api",
        rights_status="public",
        model_eligible=True,
        frequency="daily",
    )
    assert e.model_eligible is True


def test_eligible_for_model_filters_correctly(registry):
    elig = eligible_for_model(registry)
    assert all(e.model_eligible for e in elig)
    assert all(e.rights_status == "public" for e in elig)
    # And the inverse: any non-public entry must be filtered out.
    non_public = [e for e in registry.entries if e.rights_status != "public"]
    for e in non_public:
        assert e not in elig


def test_entries_for_source_fred(registry):
    fred = entries_for_source(registry, "fred")
    assert len(fred) >= 2
    assert all(e.source == "fred" for e in fred)


def test_duplicate_key_at_registry_level_rejected():
    from v2.ingest.public_data_registry import PublicDataRegistry

    e1 = RegistryEntry(
        key="dup",
        source="a",
        description="x",
        source_url="https://example.com/x",
        retrieval_method="api",
        rights_status="public",
        model_eligible=True,
        frequency="daily",
    )
    e2 = RegistryEntry(
        key="dup",
        source="b",
        description="y",
        source_url="https://example.com/y",
        retrieval_method="api",
        rights_status="public",
        model_eligible=True,
        frequency="daily",
    )
    with pytest.raises(ValidationError):
        PublicDataRegistry(entries=[e1, e2])
