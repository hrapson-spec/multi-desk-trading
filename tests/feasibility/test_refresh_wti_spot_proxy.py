"""Tests for the forward WTI spot proxy refresh command."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from feasibility.scripts.refresh_wti_spot_proxy import (
    WTIRefreshError,
    latest_valid_price_date,
    parse_fred_dcoilwtico_csv,
    refresh_wti_spot_proxy,
)
from v2.ingest._http import HTTPResponse


class _FakeHTTP:
    def __init__(self, response: HTTPResponse) -> None:
        self.response = response
        self.calls = 0

    def get(self, *_args: Any, **_kwargs: Any) -> HTTPResponse:
        self.calls += 1
        return self.response


def _response(body: str, status_code: int = 200) -> HTTPResponse:
    return HTTPResponse(
        status_code=status_code,
        content=body.encode(),
        headers={},
        etag=None,
        last_modified=None,
        retrieved_at_utc=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )


def test_parse_fred_dcoilwtico_csv_normalizes_schema() -> None:
    frame = parse_fred_dcoilwtico_csv(
        b"DATE,DCOILWTICO\n2026-04-27,90.1\n2026-04-28,.\n2026-04-29,91.2\n"
    )

    assert list(frame.columns) == ["observation_date", "DCOILWTICO"]
    latest = latest_valid_price_date(frame)
    assert latest is not None
    assert latest.isoformat() == "2026-04-29"
    assert pd.isna(frame.loc[1, "DCOILWTICO"])


def test_refresh_writes_when_fred_data_is_fresh(tmp_path: Path) -> None:
    output = tmp_path / "DCOILWTICO.csv"
    status = tmp_path / "status.json"
    http = _FakeHTTP(_response("observation_date,DCOILWTICO\n2026-04-27,90.1\n2026-04-28,91.2\n"))

    result = refresh_wti_spot_proxy(
        output_path=output,
        status_path=status,
        as_of_date=datetime(2026, 4, 29, tzinfo=UTC).date(),
        http_client=http,
    )

    assert result.status == "refreshed"
    assert result.latest_valid_date == "2026-04-28"
    assert output.read_text().startswith("observation_date,DCOILWTICO\n")
    assert '"status": "refreshed"' in status.read_text()
    assert http.calls == 1


def test_refresh_rejects_stale_fred_data_without_overwriting(tmp_path: Path) -> None:
    output = tmp_path / "DCOILWTICO.csv"
    output.write_text("observation_date,DCOILWTICO\n2026-04-20,91.06\n")
    status = tmp_path / "status.json"
    http = _FakeHTTP(_response("observation_date,DCOILWTICO\n2026-04-20,91.06\n"))

    with pytest.raises(WTIRefreshError, match="days old"):
        refresh_wti_spot_proxy(
            output_path=output,
            status_path=status,
            as_of_date=datetime(2026, 4, 29, tzinfo=UTC).date(),
            http_client=http,
        )

    assert output.read_text() == "observation_date,DCOILWTICO\n2026-04-20,91.06\n"
    assert '"status": "failed"' in status.read_text()
    assert '"latest_valid_date": "2026-04-20"' in status.read_text()


def test_refresh_rejects_non_200_response(tmp_path: Path) -> None:
    http = _FakeHTTP(_response("rate limited", status_code=429))

    with pytest.raises(WTIRefreshError, match="HTTP 429"):
        refresh_wti_spot_proxy(
            output_path=tmp_path / "DCOILWTICO.csv",
            status_path=tmp_path / "status.json",
            as_of_date=datetime(2026, 4, 29, tzinfo=UTC).date(),
            http_client=http,
        )


def test_refresh_rejects_malformed_csv(tmp_path: Path) -> None:
    http = _FakeHTTP(_response("not_the,right_columns\n1,2\n"))

    with pytest.raises(WTIRefreshError, match="must contain"):
        refresh_wti_spot_proxy(
            output_path=tmp_path / "DCOILWTICO.csv",
            status_path=tmp_path / "status.json",
            as_of_date=datetime(2026, 4, 29, tzinfo=UTC).date(),
            http_client=http,
        )
