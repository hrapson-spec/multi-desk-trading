"""Refresh the FRED DCOILWTICO spot proxy used by forward WTI evidence."""

from __future__ import annotations

import argparse
import io
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, cast

import pandas as pd

from v2.ingest._http import HTTPClient

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WTI_CSV = REPO_ROOT / "data/s4_0/free_source/raw/DCOILWTICO.csv"
DEFAULT_STATUS_JSON = REPO_ROOT / "feasibility/forward/wti_lag_1d/wti_spot_refresh_status.json"
FRED_DCOILWTICO_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_DCOILWTICO_PARAMS = {"id": "DCOILWTICO"}
DEFAULT_MAX_FEATURE_AGE_DAYS = 4


class WTIRefreshError(RuntimeError):
    """Raised when the WTI spot proxy cannot be refreshed to a usable state."""


@dataclass(frozen=True)
class WTIRefreshResult:
    status: str
    source_url: str
    output_path: str
    retrieved_at_utc: str
    as_of_date: str
    max_feature_age_days: int
    rows: int
    valid_price_rows: int
    latest_valid_date: str | None
    age_days: int | None
    error: str | None = None


def parse_fred_dcoilwtico_csv(content: bytes) -> pd.DataFrame:
    """Parse FRED graph CSV bytes into the locked local proxy schema."""
    if not content.strip():
        raise WTIRefreshError("FRED DCOILWTICO response body was empty")

    frame = pd.read_csv(io.BytesIO(content))
    fields = set(frame.columns)
    date_col = "observation_date" if "observation_date" in fields else "DATE"
    if date_col not in fields or "DCOILWTICO" not in fields:
        raise WTIRefreshError(
            "FRED DCOILWTICO CSV must contain observation_date/DATE and DCOILWTICO"
        )

    dates = pd.to_datetime(frame[date_col], errors="coerce")
    values = pd.to_numeric(frame["DCOILWTICO"].replace(".", pd.NA), errors="coerce")
    out = pd.DataFrame(
        {
            "observation_date": dates.dt.strftime("%Y-%m-%d"),
            "DCOILWTICO": values,
        }
    )
    out = out[out["observation_date"].notna()]
    if out.empty:
        raise WTIRefreshError("FRED DCOILWTICO CSV contained no valid observation dates")
    return (
        out.sort_values("observation_date")
        .drop_duplicates("observation_date", keep="last")
        .reset_index(drop=True)
    )


def latest_valid_price_date(frame: pd.DataFrame) -> date | None:
    valid = frame[pd.to_numeric(frame["DCOILWTICO"], errors="coerce").notna()]
    if valid.empty:
        return None
    latest = pd.Timestamp(valid["observation_date"].max())
    return cast(date, latest.date())


def _write_status(path: Path, result: WTIRefreshResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(result), indent=2, sort_keys=True) + "\n")


def _write_proxy_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.tmp")
    frame.to_csv(tmp_path, index=False, float_format="%.10g")
    tmp_path.replace(path)


def _source_label() -> str:
    return f"{FRED_DCOILWTICO_CSV_URL}?id=DCOILWTICO"


def _display_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT))
    except ValueError:
        return str(resolved)


def _result(
    *,
    status: str,
    output_path: Path,
    retrieved_at_utc: datetime,
    as_of_date: date,
    max_feature_age_days: int,
    frame: pd.DataFrame | None = None,
    error: str | None = None,
) -> WTIRefreshResult:
    latest = latest_valid_price_date(frame) if frame is not None else None
    age_days = (as_of_date - latest).days if latest is not None else None
    return WTIRefreshResult(
        status=status,
        source_url=_source_label(),
        output_path=_display_path(output_path),
        retrieved_at_utc=retrieved_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        as_of_date=as_of_date.isoformat(),
        max_feature_age_days=max_feature_age_days,
        rows=0 if frame is None else int(len(frame)),
        valid_price_rows=(
            0
            if frame is None
            else int(pd.to_numeric(frame["DCOILWTICO"], errors="coerce").notna().sum())
        ),
        latest_valid_date=None if latest is None else latest.isoformat(),
        age_days=age_days,
        error=error,
    )


def refresh_wti_spot_proxy(
    *,
    output_path: Path = DEFAULT_WTI_CSV,
    status_path: Path = DEFAULT_STATUS_JSON,
    max_feature_age_days: int = DEFAULT_MAX_FEATURE_AGE_DAYS,
    as_of_date: date | None = None,
    http_client: Any | None = None,
    timeout_seconds: float = 30.0,
) -> WTIRefreshResult:
    """Fetch FRED DCOILWTICO, validate freshness, and atomically replace the CSV."""
    observed_as_of = as_of_date or datetime.now(UTC).date()
    retrieved_at = datetime.now(UTC)
    client = http_client or HTTPClient(timeout=timeout_seconds, max_retries=2)
    close_client = http_client is None
    try:
        # NOTE 2026-04-29: do NOT pass a custom User-Agent to FRED's
        # graph/fredgraph.csv endpoint. Empirically, FRED's CDN silently
        # sinkholes (read-timeout) requests with non-mainstream UAs.
        # The default httpx UA passes through; a custom UA does not.
        # Diagnosed via direct probe: same URL/params/timeout, only
        # difference is the User-Agent header → 200 OK vs 30s timeout.
        response = client.get(
            FRED_DCOILWTICO_CSV_URL,
            params=FRED_DCOILWTICO_PARAMS,
        )
        if response.status_code != 200:
            raise WTIRefreshError(f"FRED DCOILWTICO returned HTTP {response.status_code}")
        frame = parse_fred_dcoilwtico_csv(response.content)
        latest = latest_valid_price_date(frame)
        if latest is None:
            raise WTIRefreshError("FRED DCOILWTICO CSV contained no valid prices")
        age_days = (observed_as_of - latest).days
        if age_days > max_feature_age_days:
            raise WTIRefreshError(
                f"latest valid DCOILWTICO date {latest.isoformat()} is "
                f"{age_days} days old; max allowed is {max_feature_age_days}"
            )
        _write_proxy_csv(output_path, frame)
        result = _result(
            status="refreshed",
            output_path=output_path,
            retrieved_at_utc=retrieved_at,
            as_of_date=observed_as_of,
            max_feature_age_days=max_feature_age_days,
            frame=frame,
        )
        _write_status(status_path, result)
        return result
    except Exception as exc:
        error = str(exc)
        result = _result(
            status="failed",
            output_path=output_path,
            retrieved_at_utc=retrieved_at,
            as_of_date=observed_as_of,
            max_feature_age_days=max_feature_age_days,
            error=error,
        )
        if "frame" in locals():
            result = _result(
                status="failed",
                output_path=output_path,
                retrieved_at_utc=retrieved_at,
                as_of_date=observed_as_of,
                max_feature_age_days=max_feature_age_days,
                frame=frame,
                error=error,
            )
        _write_status(status_path, result)
        if isinstance(exc, WTIRefreshError):
            raise
        raise WTIRefreshError(error) from exc
    finally:
        if close_client:
            client.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_WTI_CSV)
    parser.add_argument("--status-output", type=Path, default=DEFAULT_STATUS_JSON)
    parser.add_argument("--max-feature-age-days", type=int, default=DEFAULT_MAX_FEATURE_AGE_DAYS)
    parser.add_argument("--as-of-date", type=lambda value: date.fromisoformat(value))
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args(argv)

    try:
        result = refresh_wti_spot_proxy(
            output_path=args.output,
            status_path=args.status_output,
            max_feature_age_days=args.max_feature_age_days,
            as_of_date=args.as_of_date,
            timeout_seconds=args.timeout_seconds,
        )
    except WTIRefreshError as exc:
        print(f"wti_spot_refresh_failed={exc}")
        print(f"status={args.status_output}")
        return 2

    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
