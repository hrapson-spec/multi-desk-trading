"""Foundation tests for the operator-secrets loader (Phase B2b Wave 0)."""

from __future__ import annotations

from pathlib import Path

import pytest

from v2.ingest._secrets import (
    MissingAPIKeyError,
    get_api_key,
    load_operator_config,
)


def test_missing_key_raises_with_runbook_ref(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "operator.yaml"
    cfg.write_text("other_key: zzz\n")
    monkeypatch.setenv("V2_OPERATOR_CONFIG", str(cfg))
    with pytest.raises(MissingAPIKeyError) as ei:
        get_api_key("fred")
    assert "operator_runbook_public_data.md" in str(ei.value)


def test_env_var_override_honoured(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "operator.yaml"
    cfg.write_text("fred_api_key: sekret-abc-123\n")
    monkeypatch.setenv("V2_OPERATOR_CONFIG", str(cfg))
    assert get_api_key("fred") == "sekret-abc-123"


def test_missing_config_file_returns_empty_dict(tmp_path: Path, monkeypatch):
    nonexistent = tmp_path / "does-not-exist.yaml"
    monkeypatch.setenv("V2_OPERATOR_CONFIG", str(nonexistent))
    assert load_operator_config() == {}


def test_explicit_path_overrides_env(tmp_path: Path, monkeypatch):
    env_cfg = tmp_path / "env.yaml"
    env_cfg.write_text("fred_api_key: from-env\n")
    explicit_cfg = tmp_path / "explicit.yaml"
    explicit_cfg.write_text("fred_api_key: from-explicit\n")
    monkeypatch.setenv("V2_OPERATOR_CONFIG", str(env_cfg))
    assert get_api_key("fred", path=explicit_cfg) == "from-explicit"
