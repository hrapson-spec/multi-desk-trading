"""Operator-secret loader for v2 public-data ingesters.

Default config path: ``~/.config/v2/operator.yaml``. Override with
``V2_OPERATOR_CONFIG``.

Design choices:
- Missing config file is **not** an error (returns ``{}``). This lets
  unit tests run without provisioning secrets.
- Missing key **is** an error (``MissingAPIKeyError``) with an explicit
  pointer to the operator runbook.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "v2" / "operator.yaml"
RUNBOOK_REF = "docs/v2/operator_runbook_public_data.md"


class MissingAPIKeyError(KeyError):
    """Raised when an API key is requested but not provided in operator config."""


def load_operator_config(path: Path | None = None) -> dict[str, Any]:
    """Read the operator YAML; return ``{}`` if the file is absent.

    The env var ``V2_OPERATOR_CONFIG`` overrides the default path
    (used by tests via monkeypatch).
    """
    if path is None:
        env_override = os.environ.get("V2_OPERATOR_CONFIG")
        path = Path(env_override) if env_override else DEFAULT_CONFIG_PATH

    if not path.exists():
        return {}

    with path.open("r", encoding="utf-8") as fh:
        loaded = yaml.safe_load(fh) or {}
    if not isinstance(loaded, dict):
        raise ValueError(
            f"operator config at {path} must be a YAML mapping, got {type(loaded).__name__}"
        )
    return loaded


def get_api_key(source: str, *, path: Path | None = None) -> str:
    """Look up ``f'{source}_api_key'`` in operator config; raise if missing."""
    cfg = load_operator_config(path=path)
    key_name = f"{source}_api_key"
    val = cfg.get(key_name)
    if not val:
        raise MissingAPIKeyError(
            f"missing operator key {key_name!r}; see {RUNBOOK_REF} for provisioning steps"
        )
    return str(val)
