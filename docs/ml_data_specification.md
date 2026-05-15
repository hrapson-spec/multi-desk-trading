# ML Training Data Specification — WTI Oil Desks

Surveyed 2026-05-15. Three sources confirmed: Databento (market data), EIA API (fundamentals), FRED API (macro).

## Summary verdict

**Yes, this is sufficient to train the ridge models in `desks/`**, with one constraint: the common window is 2019-01-01 → present (limited by IFEU Brent starting 2018-12-23 and ICE confirming 2019 as safe). For features that don't need Brent, the window extends to 2010 (Databento) or 1982 (EIA) giving ~2,200+ weekly observations.

The honest sample size constraint: **~350–360 non-overlapping 1-week observations** in the 2019–2026 window. That is fine for ridge regression (the chosen model class) but rules out nonlinear models with many parameters.

---

## Feature registry by desk

### `storage_curve` desk — target: `WTI_FRONT_1W_LOG_RETURN`

These are the most directly predictive features. EIA stocks are the physical reality; the futures curve is the market's price of that reality.

| Feature | Source | Series/Symbol | Freq | History |
|---|---|---|---|---|
| **Cushing crude stocks (level)** | EIA | `WCSSTUS1` | Weekly (Fri) | 1982 |
| **Cushing stocks YoY change** | EIA | derived from above | Weekly | 1983 |
| **US total crude excl SPR (level)** | EIA | `WCESTUS1` | Weekly (Fri) | 1982 |
| **US crude stocks 5yr seasonal deviation** | EIA | derived | Weekly | 1987 |
| **Implied crude supply/demand balance** | EIA | `WCESTUS1` Δ week | Weekly | 1982 |
| **1-month roll yield** | Databento | `(CL.c.0 - CL.c.1) / CL.c.1` | Daily | 2010 |
| **Full curve slope (1M–12M)** | Databento | `(CL.c.0 - CL.c.11) / CL.c.11` | Daily | 2010 |
| **Curve belly (3M–avg(1M,6M))** | Databento | `CL.c.3 - 0.5*(CL.c.1+CL.c.5)` | Daily | 2010 |
| **Roll yield momentum (4w ∆)** | Databento | derived | Daily | 2010 |
| **Distillate stocks (level)** | EIA | `WDISTUS1` | Weekly (Fri) | 1982 |
| **SPR direction (release/refill)** | EIA | `WCSSPRUS1` Δ | Weekly | ~2000 |

**Release timing note**: EIA WPSR data has `period` = Friday end-of-week. The actual release is **Wednesday ~10:30 AM EST** for the preceding Friday's snapshot. Features must be lagged by 5 days (the Wednesday-after-Friday-reference) to avoid lookahead bias in weekly return prediction.

---

### `oil_demand_nowcast` desk — target: `WTI_FRONT_1W_LOG_RETURN`

Refinery margins and product balances are the best real-time demand proxies available.

| Feature | Source | Series/Symbol | Freq | History |
|---|---|---|---|---|
| **3-2-1 crack spread** | Databento | `(2×RB.c.0 + HO.c.0 − 3×CL.c.0)/3` | Daily | 2010 |
| **Gasoline crack (RB-CL)** | Databento | `RB.c.0 − CL.c.0` | Daily | 2010 |
| **Distillate crack (HO-CL)** | Databento | `HO.c.0 − CL.c.0` | Daily | 2010 |
| **Refinery utilization rate** | EIA | `WCRRIUS2` | Weekly (Fri) | 1982 |
| **Total products supplied (4w MA)** | EIA | `WTTNTUS2` | Weekly (Fri) | 1991 |
| **Gasoline products supplied** | EIA | `WGFUPUS2` | Weekly (Fri) | 1991 |
| **Gasoline retail price** | FRED | `GASALLW` | Weekly (Mon) | 1993 |
| **US crude production (monthly)** | EIA | `MCRFPUS2` | Monthly | 1920 |
| **Industrial production** | FRED | `INDPRO` | Monthly | 1919 |
| **Kilian global activity index** | FRED | `IGREA` | Monthly | 1968 |
| **Manufacturing employment (proxy PMI)** | FRED | `MANEMP` | Monthly | 1939 |

---

### `supply_disruption_news` desk — target: `WTI_FRONT_1W_LOG_RETURN`

Supply signals without a news feed. These are all *lagging* reaction signals — the desk will have limited predictive power on this basis alone (logged as a capability debit).

| Feature | Source | Series/Symbol | Freq | History |
|---|---|---|---|---|
| **Brent-WTI spread** | Databento | `BRN.c.0 − CL.c.0` | Daily | 2019 |
| **Brent 1M roll yield** | Databento | `(BRN.c.0 − BRN.c.1)/BRN.c.1` | Daily | 2019 |
| **Brent-WTI spread 4w ∆** | Databento | derived | Daily | 2019 |
| **US crude net imports** | EIA | `WCRNTUS2` | Weekly (Fri) | 2001 |
| **US rotary rig count** | EIA | `E_ERTRR0_XR0_NUS_C` | Monthly | ~1999 |
| **Henry Hub natural gas spot** | FRED | `DHHNGSP` | Daily | 1997 |
| **NG–oil energy equivalence spread** | FRED/Databento | `DHHNGSP × 6 − DCOILWTICO` | Daily | 1997 |

---

### `regime_classifier` — cross-cutting

| Feature | Source | Series/Symbol | Freq | History |
|---|---|---|---|---|
| **VIX level** | FRED | `VIXCLS` | Daily | 1990 |
| **VIX 30d change** | FRED | derived | Daily | 1990 |
| **10yr Treasury yield** | FRED | `DGS10` | Daily | 1962 |
| **2s10s yield curve slope** | FRED | `DGS10 − DGS2` | Daily | 1976 |
| **USD broad index** | FRED | `DTWEXBGS` | Daily | 2006 |
| **USD 4-week momentum** | FRED | derived | Daily | 2006 |
| **CPI YoY (inflation regime)** | FRED | `CPIAUCSL` | Monthly | 1947 |
| **S&P 500 30d return** | FRED | `SP500` | Daily | 2016* |

*SP500 on FRED only goes back to 2016. Use `^GSPC` via yfinance or compute from FRED `SP500` for the full history — not a dependency blocker since VIX is the primary regime signal.

---

## Recommended training window and sample count

| Scenario | Window | ~Weekly obs | Notes |
|---|---|---|---|
| **Brent-inclusive (full feature set)** | 2019-01 → 2026-05 | ~380 | Required for supply desk Brent features |
| **Databento + EIA only** | 2014-01 → 2026-05 | ~640 | No Brent; all EIA fundamentals + WTI curve |
| **EIA + FRED only (no Databento)** | 2006-01 → 2026-05 | ~1,050 | No term structure; use FRED WTI spot only |
| **EIA fundamentals only** | 1993-01 → 2026-05 | ~1,720 | Longest; no intraday/curve signals |

**Recommended**: train on **2014–2026** window (~640 obs) using Databento curve + EIA weekly + FRED macro. Reserve Brent-dependent features for the supply desk only, which will have a shorter effective history.

---

## Fetch specification

### Databento (cost: ~$0.50 total)
```python
GLBX_SYMBOLS = [f'CL.c.{i}' for i in range(12)] + ['HO.c.0','HO.c.1','RB.c.0','RB.c.1','NG.c.0','NG.c.1']
IFEU_SYMBOLS = ['BRN.c.0','BRN.c.1','BRN.c.2']
SCHEMA = 'ohlcv-1d'
START, END = '2014-01-01', '2026-05-14'
```

### EIA API (free)
```python
EIA_WEEKLY = {
    'petroleum/stoc/wstk/data/': ['WCESTUS1','WCSSTUS1','WDISTUS1','WGTSTUS1'],
    'petroleum/pnp/wiup/data/':  ['WCRRIUS2'],
    'petroleum/move/wkly/data/': ['WCRNTUS2','WTTNTUS2'],
    'petroleum/cons/wpsup/data/': ['WGFUPUS2'],
}
EIA_MONTHLY = {
    'petroleum/crd/crpdn/data/': ['MCRFPUS2'],  # US crude production
    'petroleum/crd/drill/data/': ['E_ERTRR0_XR0_NUS_C'],  # rig count
}
```

### FRED API (free)
```python
FRED_DAILY   = ['VIXCLS','DTWEXBGS','DGS10','DGS2','DCOILWTICO','DCOILBRENTEU','DHHNGSP','SP500']
FRED_WEEKLY  = ['GASALLW']
FRED_MONTHLY = ['INDPRO','CPIAUCSL','FEDFUNDS','IGREA','MANEMP']
```

---

## What this data cannot do

1. **OPEC decision prediction**: Nothing here gives advance warning of OPEC+ meeting outcomes. The Brent-WTI spread reacts within hours of announcements; it cannot predict them.

2. **Cushing pipeline/infrastructure events**: Stocks data reflects outages ex-post. No predictive signal here.

3. **Weekly EIA surprise (consensus vs actual)**: The signal in EIA releases is the *surprise* relative to analyst consensus. Without a consensus estimate feed (Bloomberg, Reuters), you can only use the raw level/change — missing roughly half the tradeable information in the report.

4. **Vessel tracking / tanker flow**: Kpler/Vortexa data (banned per §1.2) gives 1–3 week leading insight into import flows. `WCRNTUS2` is a 7-10 day lagged version of this.

5. **Non-US supply shocks**: Iranian, Venezuelan, Russian disruptions show up in Brent-WTI spread with delay, not leading.

Items 3 and 5 should be opened as capability debits in `docs/capability_debits.md` for the supply desk.
