"""End-to-end test: PIT store → FeatureView → prompt_balance_nowcast desk → ForecastV2."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from v2.contracts import ForecastV2
from v2.desks.base import DeskV2
from v2.desks.oil.prompt_balance_nowcast import PromptBalanceNowcastDesk
from v2.feature_view import build_feature_view
from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter

REQUIRED_SERIES = (
    "crude_stocks",
    "gasoline_stocks",
    "distillate_stocks",
    "refinery_runs",
    "crude_imports",
    "crude_exports",
)


@pytest.fixture
def populated_store(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    r = PITReader(tmp_path, m)
    release_ts = datetime(2026, 4, 22, 14, 30, tzinfo=UTC)
    for s in REQUIRED_SERIES:
        w.write_vintage(
            source="eia_wpsr",
            series=s,
            release_ts=release_ts,
            data=pd.DataFrame({"value": [1.0]}),
            provenance={"source": "eia_wpsr", "method": "test"},
        )
    try:
        yield tmp_path, w, m, r
    finally:
        m.close()


def test_desk_satisfies_protocol():
    desk = PromptBalanceNowcastDesk()
    assert isinstance(desk, DeskV2)
    assert desk.family_id == "oil_wti_5d"
    assert desk.desk_id == "prompt_balance_nowcast"
    assert len(desk.feature_specs()) == 7


def test_desk_emits_valid_forecast_when_features_available(populated_store):
    _root, _w, _m, reader = populated_store
    desk = PromptBalanceNowcastDesk()
    view = build_feature_view(
        as_of_ts=datetime(2026, 4, 23, 21, 0, tzinfo=UTC),
        family=desk.family_id,
        desk=desk.desk_id,
        specs=desk.feature_specs(),
        reader=reader,
    )
    fct = desk.forecast(view, prereg_hash="sha256:prereg", code_commit="abcdef0")
    assert isinstance(fct, ForecastV2)
    assert fct.abstain is False
    assert fct.target_variable == "WTI_FRONT_1W_LOG_RETURN"
    assert fct.feature_view_hash == view.view_hash
    assert fct.prereg_hash == "sha256:prereg"
    assert fct.code_commit == "abcdef0"
    # Monotone (scaffold is Gaussian, so sorted by construction).
    assert list(fct.quantile_vector) == sorted(fct.quantile_vector)


def test_desk_abstains_when_required_feature_missing(tmp_path):
    m = open_manifest(tmp_path)
    w = PITWriter(tmp_path, m)
    # Only ingest 3 of the 6 required series — desk must abstain.
    for s in REQUIRED_SERIES[:3]:
        w.write_vintage(
            source="eia_wpsr",
            series=s,
            release_ts=datetime(2026, 4, 22, 14, 30, tzinfo=UTC),
            data=pd.DataFrame({"value": [1.0]}),
            provenance={"source": "eia_wpsr", "method": "test"},
        )
    reader = PITReader(tmp_path, m)

    desk = PromptBalanceNowcastDesk()
    view = build_feature_view(
        as_of_ts=datetime(2026, 4, 23, 21, 0, tzinfo=UTC),
        family=desk.family_id,
        desk=desk.desk_id,
        specs=desk.feature_specs(),
        reader=reader,
    )
    fct = desk.forecast(view, prereg_hash="sha256:prereg", code_commit="abcdef0")
    assert fct.abstain is True
    assert fct.abstain_reason is not None
    assert "missing" in fct.abstain_reason.lower()
    m.close()


def test_forecast_view_hash_binds_to_view(populated_store):
    """Same code_commit + prereg_hash but different views → different forecasts."""
    _root, _w, _m, reader = populated_store
    desk = PromptBalanceNowcastDesk()
    v1 = build_feature_view(
        as_of_ts=datetime(2026, 4, 23, 21, 0, tzinfo=UTC),
        family=desk.family_id,
        desk=desk.desk_id,
        specs=desk.feature_specs(),
        reader=reader,
    )
    v2 = build_feature_view(
        as_of_ts=datetime(2026, 4, 24, 21, 0, tzinfo=UTC),
        family=desk.family_id,
        desk=desk.desk_id,
        specs=desk.feature_specs(),
        reader=reader,
    )
    assert v1.view_hash != v2.view_hash
    f1 = desk.forecast(v1, prereg_hash="p", code_commit="c")
    f2 = desk.forecast(v2, prereg_hash="p", code_commit="c")
    assert f1.feature_view_hash != f2.feature_view_hash
