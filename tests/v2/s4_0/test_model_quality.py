"""WTI local/free model-quality diagnostic tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from v2.s4_0.model_quality import (
    WTIModelQualityParams,
    load_wti_price_series,
    run_wti_model_quality_diagnostic,
)


def test_model_quality_diagnostic_beats_baselines_on_predictable_fixture(tmp_path):
    path = _predictable_wti_csv(tmp_path, n=900)

    report = run_wti_model_quality_diagnostic(
        path,
        WTIModelQualityParams(
            warmup_days=260,
            min_train_samples=120,
            horizon_days=5,
            ridge_alpha=1.0,
        ),
    )

    assert report.ok is True
    assert report.decisions > 500
    assert report.model_beats_empirical_pinball is True
    assert report.model_beats_zero_gaussian_pinball is True
    assert report.model_beats_empirical_crps is True
    assert report.model_beats_zero_gaussian_crps is True
    assert report.pinball_improvement_vs_empirical > 0
    assert report.pinball_improvement_vs_zero_gaussian > 0
    assert report.directional_accuracy > 0.55
    assert report.promoted_for_research is True
    assert report.as_dict()["result_hash"] == report.result_hash
    assert "not a live trading result" in report.non_claims


def test_model_quality_diagnostic_is_deterministic(tmp_path):
    path = _predictable_wti_csv(tmp_path, n=500)
    params = WTIModelQualityParams(
        warmup_days=180,
        min_train_samples=90,
        horizon_days=5,
        ridge_alpha=2.0,
    )

    first = run_wti_model_quality_diagnostic(path, params)
    second = run_wti_model_quality_diagnostic(path, params)

    assert first.result_hash == second.result_hash
    assert first.as_dict() == second.as_dict()


def test_model_quality_loader_accepts_s4_replay_style_csv(tmp_path):
    path = tmp_path / "replay.csv"
    path.write_text(
        "\n".join(
            [
                "ts_event,ts_recv,symbol,price,size,sequence",
                "2026-04-01T21:00:00Z,2026-04-01T21:00:01Z,CL,70,1,1",
                "2026-04-02T21:00:00Z,2026-04-02T21:00:01Z,CL,71,1,2",
                "2026-04-03T21:00:00Z,2026-04-03T21:00:01Z,CL,72,1,3",
                "2026-04-06T21:00:00Z,2026-04-06T21:00:01Z,CL,73,1,4",
                "2026-04-07T21:00:00Z,2026-04-07T21:00:01Z,CL,74,1,5",
                "2026-04-08T21:00:00Z,2026-04-08T21:00:01Z,CL,75,1,6",
                "2026-04-09T21:00:00Z,2026-04-09T21:00:01Z,CL,76,1,7",
                "2026-04-10T21:00:00Z,2026-04-10T21:00:01Z,CL,77,1,8",
                "2026-04-13T21:00:00Z,2026-04-13T21:00:01Z,CL,78,1,9",
                "2026-04-14T21:00:00Z,2026-04-14T21:00:01Z,CL,79,1,10",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    series = load_wti_price_series(path)

    assert len(series) == 10
    assert series.iloc[0] == 70
    assert str(series.index.tz) == "UTC"


def test_model_quality_rejects_short_series(tmp_path):
    path = _predictable_wti_csv(tmp_path, n=80)

    with pytest.raises(ValueError, match="not enough rows"):
        run_wti_model_quality_diagnostic(
            path,
            WTIModelQualityParams(warmup_days=60, min_train_samples=30),
        )


def _predictable_wti_csv(tmp_path, *, n: int):
    rng = np.random.default_rng(7)
    index = pd.date_range("2020-01-01", periods=n, freq="B")
    returns = np.zeros(n)
    returns[:20] = rng.normal(0, 0.004, 20)
    for i in range(20, n):
        signal = 0.35 * returns[i - 1] + 0.20 * returns[i - 5]
        returns[i] = signal + rng.normal(0, 0.003)
    price = 60 * np.exp(np.cumsum(returns))
    path = tmp_path / "DCOILWTICO.csv"
    rows = ["observation_date,DCOILWTICO"]
    rows.extend(
        f"{ts.date().isoformat()},{value:.8f}"
        for ts, value in zip(index, price, strict=True)
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path
