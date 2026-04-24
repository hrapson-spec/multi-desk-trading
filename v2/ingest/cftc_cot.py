"""CFTC Commitments of Traders ingester and WTI feature normalizer.

Release cadence: Friday >=15:30 ET (calendar: cftc_cot.yaml).
Observation semantics: positions as of Tuesday prior.

Network implementation: deferred. CFTC publishes structured CSV archives
at https://www.cftc.gov/dea/newcot/deacot.txt (current) and
https://www.cftc.gov/MarketReports/CommitmentsofTraders/HistoricalCompressed/index.htm
(historical annuals). Both are free and open.

Operator action required before promotion:
    1. Implement CFTCCOTIngester.fetch to pull the disaggregated,
       futures-only WTI contract code (currently '067651' for CL on
       NYMEX — verify).
    2. Explicitly set release_ts to the publisher's release_ts on
       Friday 15:30 ET; never ingest with a release_ts earlier than
       that, even if the CSV appears on the server earlier.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from v2.ingest.base import BaseIngester

WTI_CFTC_CONTRACT_MARKET_CODE = "067651"
_NY = ZoneInfo("America/New_York")


class CFTCCOTIngester(BaseIngester):
    name = "cftc_cot"
    source = "cftc_cot"


def normalize_wti_disaggregated_cot(
    data: pd.DataFrame | Path,
    *,
    market_code: str = WTI_CFTC_CONTRACT_MARKET_CODE,
) -> pd.DataFrame:
    """Return PIT-eligible WTI COT features indexed by release timestamp.

    The input is the CFTC disaggregated futures-only historical text/CSV shape.
    The output index is Friday 15:30 America/New_York converted to UTC, not the
    Tuesday report date. This makes the frame safe for backward-as-of merging
    into decision rows.
    """
    frame = pd.read_csv(data) if isinstance(data, Path) else data.copy()
    code_col = _first_present(
        frame,
        "CFTC_Contract_Market_Code",
        "CFTC_Contract_Market_Code_Quotes",
    )
    date_col = _first_present(
        frame,
        "As_of_Date_Form_MM/DD/YYYY",
        "Report_Date_as_MM_DD_YYYY",
    )
    required = [
        code_col,
        date_col,
        "Open_Interest_All",
        "Prod_Merc_Positions_Long_All",
        "Prod_Merc_Positions_Short_All",
        "Swap_Positions_Long_All",
        "Swap__Positions_Short_All",
        "M_Money_Positions_Long_All",
        "M_Money_Positions_Short_All",
        "Other_Rept_Positions_Long_All",
        "Other_Rept_Positions_Short_All",
        "NonRept_Positions_Long_All",
        "NonRept_Positions_Short_All",
    ]
    missing = [name for name in required if name not in frame.columns]
    if missing:
        raise ValueError("CFTC COT frame missing columns: " + ", ".join(missing))

    filtered = frame[
        frame[code_col].astype(str).str.strip().str.strip("'\"") == market_code
    ].copy()
    if filtered.empty:
        raise ValueError(f"no CFTC COT rows for market code {market_code}")

    report_date = pd.to_datetime(filtered[date_col], errors="coerce")
    if report_date.isna().any():
        raise ValueError("CFTC COT report date parse failed")

    numeric_cols = [name for name in required if name not in {code_col, date_col}]
    for col in numeric_cols:
        filtered[col] = _numeric(filtered[col])

    output = pd.DataFrame(index=filtered.index)
    output["report_date"] = report_date.dt.date
    output["open_interest"] = filtered["Open_Interest_All"]
    output["prod_merc_net"] = (
        filtered["Prod_Merc_Positions_Long_All"]
        - filtered["Prod_Merc_Positions_Short_All"]
    )
    output["swap_net"] = (
        filtered["Swap_Positions_Long_All"]
        - filtered["Swap__Positions_Short_All"]
    )
    output["managed_money_net"] = (
        filtered["M_Money_Positions_Long_All"]
        - filtered["M_Money_Positions_Short_All"]
    )
    output["other_reportable_net"] = (
        filtered["Other_Rept_Positions_Long_All"]
        - filtered["Other_Rept_Positions_Short_All"]
    )
    output["nonreportable_net"] = (
        filtered["NonRept_Positions_Long_All"]
        - filtered["NonRept_Positions_Short_All"]
    )
    for col in [
        "prod_merc_net",
        "swap_net",
        "managed_money_net",
        "other_reportable_net",
        "nonreportable_net",
    ]:
        output[f"{col}_oi"] = output[col] / output["open_interest"].replace(0, pd.NA)

    release_ts = [
        _cot_release_ts(pd.Timestamp(item).to_pydatetime())
        for item in report_date
    ]
    output.index = pd.DatetimeIndex(release_ts, name="release_ts")
    output = output.sort_index()
    output = output[~output.index.duplicated(keep="last")]
    return output


def _cot_release_ts(report_date: datetime) -> datetime:
    report_day = report_date.date()
    days_until_friday = (4 - report_day.weekday()) % 7
    release_day = report_day + timedelta(days=days_until_friday)
    local = datetime.combine(release_day, time(15, 30), tzinfo=_NY)
    return local.astimezone(UTC)


def _numeric(values: pd.Series) -> pd.Series:
    return pd.to_numeric(
        values.astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )


def _first_present(frame: pd.DataFrame, *names: str) -> str:
    for name in names:
        if name in frame.columns:
            return name
    raise ValueError("CFTC COT frame missing one of: " + ", ".join(names))
