"""CFTC COT WTI feature-normalizer tests."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from v2.ingest.cftc_cot import normalize_wti_disaggregated_cot


def test_normalize_wti_disaggregated_cot_filters_code_and_builds_features():
    frame = _cot_frame()

    features = normalize_wti_disaggregated_cot(frame)

    assert len(features) == 1
    assert features.index[0] == datetime(2026, 4, 24, 19, 30, tzinfo=UTC)
    row = features.iloc[0]
    assert row["open_interest"] == 1000
    assert row["prod_merc_net"] == -200
    assert row["swap_net"] == 25
    assert row["managed_money_net"] == 200
    assert row["other_reportable_net"] == -25
    assert row["nonreportable_net"] == 15
    assert row["managed_money_net_oi"] == 0.2


def test_normalize_wti_disaggregated_cot_accepts_quoted_market_code():
    frame = _cot_frame()
    frame.loc[0, "CFTC_Contract_Market_Code"] = "'067651'"

    features = normalize_wti_disaggregated_cot(frame)

    assert len(features) == 1
    assert features.iloc[0]["managed_money_net"] == 200


def test_normalize_wti_disaggregated_cot_rejects_missing_columns():
    frame = _cot_frame().drop(columns=["Open_Interest_All"])

    with pytest.raises(ValueError, match="missing columns"):
        normalize_wti_disaggregated_cot(frame)


def test_normalize_wti_disaggregated_cot_rejects_missing_market_code():
    frame = _cot_frame()

    with pytest.raises(ValueError, match="no CFTC COT rows"):
        normalize_wti_disaggregated_cot(frame, market_code="000000")


def _cot_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Market_and_Exchange_Names": "CRUDE OIL, LIGHT SWEET - NYMEX",
                "As_of_Date_Form_MM/DD/YYYY": "04/21/2026",
                "CFTC_Contract_Market_Code": "067651",
                "Open_Interest_All": "1,000",
                "Prod_Merc_Positions_Long_All": "100",
                "Prod_Merc_Positions_Short_All": "300",
                "Swap_Positions_Long_All": "75",
                "Swap__Positions_Short_All": "50",
                "M_Money_Positions_Long_All": "500",
                "M_Money_Positions_Short_All": "300",
                "Other_Rept_Positions_Long_All": "125",
                "Other_Rept_Positions_Short_All": "150",
                "NonRept_Positions_Long_All": "45",
                "NonRept_Positions_Short_All": "30",
            },
            {
                "Market_and_Exchange_Names": "NATURAL GAS - NYMEX",
                "As_of_Date_Form_MM/DD/YYYY": "04/21/2026",
                "CFTC_Contract_Market_Code": "023651",
                "Open_Interest_All": "2,000",
                "Prod_Merc_Positions_Long_All": "1",
                "Prod_Merc_Positions_Short_All": "2",
                "Swap_Positions_Long_All": "3",
                "Swap__Positions_Short_All": "4",
                "M_Money_Positions_Long_All": "5",
                "M_Money_Positions_Short_All": "6",
                "Other_Rept_Positions_Long_All": "7",
                "Other_Rept_Positions_Short_All": "8",
                "NonRept_Positions_Long_All": "9",
                "NonRept_Positions_Short_All": "10",
            },
        ]
    )
