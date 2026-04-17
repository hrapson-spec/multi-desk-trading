"""Provenance utilities: input-snapshot hash + code_commit resolver.

Used by desks when constructing a Provenance record. Keeps the hash
computation canonical (same inputs → same hex digest on any machine).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

BusMode = Literal["development", "production", "replay"]


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    raise TypeError(f"not JSON serialisable: {type(obj).__name__}")


def hash_input_snapshot(inputs: Sequence[Any]) -> str:
    """SHA-256 of a canonicalised JSON representation of an input sequence.

    Canonicalisation: sort_keys=True, default handler for datetimes and
    Pydantic models. Inputs must be JSON-serialisable or expose
    isoformat()/model_dump().
    """
    payload = json.dumps(list(inputs), default=_json_default, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def resolve_code_commit(mode: BusMode = "development", repo_root: Path | None = None) -> str:
    """Return the git commit SHA at repo_root, suffixed with '-dirty' iff
    there are uncommitted changes in development mode.

    In production or replay mode, a dirty working tree raises RuntimeError.
    """
    cwd = str(repo_root) if repo_root is not None else None
    sha_proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    sha = sha_proc.stdout.strip()
    status_proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    dirty = bool(status_proc.stdout.strip())
    if not dirty:
        return sha
    if mode in ("production", "replay"):
        raise RuntimeError(
            f"code_commit resolution in mode={mode!r} requires a clean working tree; "
            f"uncommitted changes detected"
        )
    return f"{sha}-dirty"


__all__ = ["BusMode", "hash_input_snapshot", "resolve_code_commit"]
