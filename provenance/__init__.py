"""Provenance utilities (spec §4.3 Provenance type)."""

from __future__ import annotations

from .hash import hash_input_snapshot, resolve_code_commit

__all__ = ["hash_input_snapshot", "resolve_code_commit"]
