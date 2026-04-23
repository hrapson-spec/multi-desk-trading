"""synthesise_family end-to-end tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from v2.contracts import CalibrationMetadata, DecisionUnit, ForecastV2
from v2.feature_view import FeatureSpec, build_feature_view
from v2.pit_store.manifest import open_manifest
from v2.pit_store.reader import PITReader
from v2.pit_store.writer import PITWriter
from v2.synthesiser import FamilyInputMismatchError, synthesise_family

_CAL = CalibrationMetadata(
    method="rolling_pinball_ratio",
    baseline_id="B0_ewma_gaussian",
    rolling_window_n=0,
    sample_count=0,
)


def _forecast(
    tmp_path: Path,
    *,
    desk_id: str = "prompt_balance_nowcast",
    quantile_vector: tuple[float, ...] = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10),
    calibration_score: float = 0.7,
    data_quality_score: float = 0.9,
    abstain: bool = False,
    abstain_reason: str | None = None,
    contract_hash: str = "sha256:contract",
    release_calendar_version: str = "eia_wpsr:1.0.0",
) -> ForecastV2:
    m = open_manifest(tmp_path)
    try:
        w = PITWriter(tmp_path, m)
        w.write_vintage(
            source="eia_wpsr",
            series="crude_stocks",
            release_ts=datetime(2026, 4, 15, 14, 30, tzinfo=UTC),
            data=pd.DataFrame({"value": [1.0]}),
            provenance={"source": "eia_wpsr", "method": "test"},
        )
        reader = PITReader(tmp_path, m)
        view = build_feature_view(
            as_of_ts=datetime(2026, 4, 22, 21, 0, tzinfo=UTC),
            family="oil_wti_5d",
            desk=desk_id,
            specs=[FeatureSpec(name="crude", source="eia_wpsr", series="crude_stocks")],
            reader=reader,
        )
        return ForecastV2.build_from_view(
            view=view,
            family_id="oil_wti_5d",
            desk_id=desk_id,
            distribution_version="0.0.1-scaffold",
            target_variable="WTI_FRONT_1W_LOG_RETURN",
            target_horizon="5d",
            decision_unit=DecisionUnit.LOG_RETURN,
            quantile_vector=quantile_vector if not abstain else tuple(0.0 for _ in range(7)),
            calibration_score=calibration_score if not abstain else 0.0,
            calibration_metadata=_CAL,
            data_quality_score=data_quality_score if not abstain else 0.0,
            valid_until_ts=datetime(2026, 4, 23, 21, 0, tzinfo=UTC),
            emitted_ts=datetime(2026, 4, 22, 21, 5, tzinfo=UTC),
            abstain=abstain,
            abstain_reason=abstain_reason,
            prereg_hash="sha256:prereg",
            code_commit="abcdef0",
            contract_hash=contract_hash,
            release_calendar_version=release_calendar_version,
        )
    finally:
        m.close()


# --- single-desk v2.0 case --------------------------------------------------


def test_single_desk_pools_to_identity(tmp_path):
    qv = (-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10)
    f = _forecast(tmp_path, quantile_vector=qv)
    fam = synthesise_family(
        [f],
        contract_hash="sha256:contract",
        release_calendar_version="eia_wpsr:1.0.0",
    )
    assert fam.abstain is False
    assert fam.quantile_vector is not None
    for a, b in zip(qv, fam.quantile_vector, strict=True):
        assert abs(a - b) < 1e-9
    assert len(fam.contributing) == 1
    assert fam.contributing[0].weight_normalised == pytest.approx(1.0)


# --- family abstain cascade -------------------------------------------------


def test_single_abstaining_desk_cascades_to_family_abstain(tmp_path):
    f = _forecast(tmp_path, abstain=True, abstain_reason="required feature missing")
    fam = synthesise_family(
        [f],
        contract_hash="sha256:contract",
        release_calendar_version="eia_wpsr:1.0.0",
    )
    assert fam.abstain is True
    assert fam.quantile_vector is None
    assert "cascade" in fam.abstain_reason
    assert f.desk_id in fam.abstaining_desk_ids
    assert not fam.contributing


def test_any_abstain_cascades_even_with_healthy_desks(tmp_path):
    f_ok = _forecast(tmp_path / "a", desk_id="good")
    f_bad = _forecast(
        tmp_path / "b",
        desk_id="broken",
        abstain=True,
        abstain_reason="stale data",
    )
    fam = synthesise_family(
        [f_ok, f_bad],
        contract_hash="sha256:contract",
        release_calendar_version="eia_wpsr:1.0.0",
    )
    assert fam.abstain is True
    assert "broken" in fam.abstaining_desk_ids


# --- desk exclusion (soft drop, not cascade) -------------------------------


def test_zero_weight_desk_excluded_not_cascaded(tmp_path):
    # Desk with zero calibration score still emits a valid non-abstain
    # forecast, but its effective weight is zero → excluded, not cascade.
    f_good = _forecast(
        tmp_path / "a",
        desk_id="good",
        quantile_vector=(-0.10, -0.05, -0.02, 0.0, 0.02, 0.05, 0.10),
        calibration_score=0.8,
        data_quality_score=0.9,
    )
    f_muted = _forecast(
        tmp_path / "b",
        desk_id="muted",
        quantile_vector=(-0.05, -0.03, -0.01, 0.0, 0.01, 0.03, 0.05),
        calibration_score=0.0,  # zero weight → excluded
        data_quality_score=0.9,
    )
    fam = synthesise_family(
        [f_good, f_muted],
        contract_hash="sha256:contract",
        release_calendar_version="eia_wpsr:1.0.0",
    )
    assert fam.abstain is False
    assert "muted" in fam.excluded_desk_ids
    assert [c.desk_id for c in fam.contributing] == ["good"]


def test_all_desks_zero_weight_triggers_family_abstain(tmp_path):
    f1 = _forecast(tmp_path / "a", desk_id="a", calibration_score=0.0)
    f2 = _forecast(tmp_path / "b", desk_id="b", data_quality_score=0.0)
    fam = synthesise_family(
        [f1, f2],
        contract_hash="sha256:contract",
        release_calendar_version="eia_wpsr:1.0.0",
    )
    assert fam.abstain is True
    assert "all desks excluded" in fam.abstain_reason
    assert set(fam.excluded_desk_ids) == {"a", "b"}


# --- regime posterior pass-through -----------------------------------------


def test_regime_posterior_defaults_to_normal(tmp_path):
    f = _forecast(tmp_path)
    fam = synthesise_family(
        [f],
        contract_hash="sha256:contract",
        release_calendar_version="eia_wpsr:1.0.0",
    )
    assert fam.regime_posterior == {"normal": 1.0}


def test_regime_posterior_passed_through(tmp_path):
    f = _forecast(tmp_path)
    fam = synthesise_family(
        [f],
        regime_posterior={"normal": 0.7, "shock": 0.3},
        contract_hash="sha256:contract",
        release_calendar_version="eia_wpsr:1.0.0",
    )
    assert fam.regime_posterior == {"normal": 0.7, "shock": 0.3}


def test_regime_posterior_not_summing_to_one_rejected(tmp_path):
    f = _forecast(tmp_path)
    with pytest.raises(ValueError, match="regime_posterior"):
        synthesise_family(
            [f],
            regime_posterior={"normal": 0.4, "shock": 0.3},
            contract_hash="sha256:contract",
            release_calendar_version="eia_wpsr:1.0.0",
        )


def test_negative_regime_posterior_rejected(tmp_path):
    f = _forecast(tmp_path)
    with pytest.raises(ValueError, match=r"\[0.0, 1.0\]"):
        synthesise_family(
            [f],
            regime_posterior={"normal": 1.2, "shock": -0.2},
            contract_hash="sha256:contract",
            release_calendar_version="eia_wpsr:1.0.0",
        )


# --- provenance consistency ------------------------------------------------


def test_family_contract_hash_must_match_inputs(tmp_path):
    f = _forecast(tmp_path, contract_hash="sha256:contract")
    with pytest.raises(FamilyInputMismatchError, match="family contract_hash"):
        synthesise_family(
            [f],
            contract_hash="sha256:made_up_family",
            release_calendar_version="eia_wpsr:1.0.0",
        )


def test_family_release_calendar_version_must_match_inputs(tmp_path):
    f = _forecast(tmp_path, release_calendar_version="eia_wpsr:1.0.0")
    with pytest.raises(FamilyInputMismatchError, match="family release_calendar_version"):
        synthesise_family(
            [f],
            contract_hash="sha256:contract",
            release_calendar_version="eia_wpsr:9.9.9",
        )


# --- provenance pass-through ------------------------------------------------


def test_family_forecast_records_contract_hash(tmp_path):
    f = _forecast(
        tmp_path,
        contract_hash="sha256:specific_contract",
        release_calendar_version="eia_wpsr:1.0.0|cftc_cot:1.0.0",
    )
    fam = synthesise_family(
        [f],
        contract_hash="sha256:specific_contract",
        release_calendar_version="eia_wpsr:1.0.0|cftc_cot:1.0.0",
    )
    assert fam.contract_hash == "sha256:specific_contract"
    assert fam.release_calendar_version == "eia_wpsr:1.0.0|cftc_cot:1.0.0"


def test_family_forecast_records_forecast_ids(tmp_path):
    f = _forecast(tmp_path)
    fam = synthesise_family(
        [f],
        contract_hash="sha256:contract",
        release_calendar_version="eia_wpsr:1.0.0",
    )
    assert len(fam.contributing) == 1
    assert fam.contributing[0].forecast_id == f.forecast_id
