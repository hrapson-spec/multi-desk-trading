"""Operator-facing rights check on the on-disk public_data_inventory.yaml.

Although the Pydantic validator already enforces the rights-gate invariant
at construction time, this test exists as the explicit contract the operator
can run before any release tag.
"""

from __future__ import annotations

from v2.ingest.public_data_registry import load_registry


def test_non_public_sources_are_not_model_eligible():
    reg = load_registry()
    for e in reg.entries:
        if e.rights_status != "public":
            assert e.model_eligible is False, (
                f"entry {e.key!r} has rights_status={e.rights_status!r} "
                f"but model_eligible=True; this is a rights-gate violation"
            )


def test_every_url_loadable():
    reg = load_registry()
    for e in reg.entries:
        # Pydantic HttpUrl coerces during load_registry; this asserts the
        # url survived as a usable string form.
        assert str(e.source_url).startswith(("http://", "https://"))
