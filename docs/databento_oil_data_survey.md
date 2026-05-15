# Databento Oil Data Survey

Surveyed 2026-05-15. Key finding: all price/volume data is very cheap (<$1 for years of daily data); tick-level MBP data is expensive and out of scope.

## Datasets available for oil

| Dataset | Exchange | Content | History |
|---------|----------|---------|---------|
| `GLBX.MDP3` | CME Globex | WTI CL, Heating Oil HO, RBOB RB, NatGas NG, Micro WTI MCL | 2010-06-06 → present |
| `IFEU.IMPACT` | ICE Futures Europe | Brent BRN | 2018-12-23 → present |
| `IFUS.IMPACT` | ICE Futures US | HH (Henry Hub NG) | 2018-12-23 → present |

All three datasets expose the same schemas: `mbo`, `mbp-1`, `mbp-10`, `tbbo`, `trades`, `bbo-1s`, `bbo-1m`, `ohlcv-1s`, `ohlcv-1m`, `ohlcv-1h`, `ohlcv-1d`, `definition`, `statistics`, `status`.

## Key symbols (all via `stype_in='continuous'`)

### WTI Crude Oil (CME Globex)
- `CL.c.0` through `CL.c.11` — 12-month forward curve, all confirmed available
- Roll yield / term structure: `CL.c.0` - `CL.c.1` daily; contango/backwardation regime clearly visible
- Jan 2024 example: 1-month roll yield ranged −0.03% to −0.31% (mild contango throughout)

### Crack Spreads (CME Globex)
- `HO.c.0` — Heating oil (proxy for distillate/diesel demand)
- `RB.c.0` — RBOB Gasoline (proxy for transportation demand)
- 3-2-1 crack = (2×RB + HO − 3×CL) / 3; all legs available

### Brent Crude (ICE Europe)
- `BRN.c.0`, `BRN.c.1`, `BRN.c.2` confirmed; back-months via `BRN.FUT` parent
- Brent-WTI spread: ~$5–6 in Jan 2024 (quality/logistics differential)

### Natural Gas (CME Globex)
- `NG.c.0`, `NG.c.1`, `NG.c.2` — front curve available; useful as energy-complex co-movement signal

### Microstructure (BBO-1m)
- `bid_px_00`, `ask_px_00`, `bid_sz_00`, `ask_sz_00`, `bid_ct_00`, `ask_ct_00`
- Gives bid-ask spread, queue depth, and order count per minute

### Open Interest (`statistics` schema, `stat_type=7`)
- Available for all continuous contracts
- Note: `quantity` field returns `2147483647` (int32 max) in some records — use `price` field for the OI level

## Cost estimates (USD, indicative)

| Data request | Cost |
|---|---|
| CL.c.0 daily OHLCV, 5 yr | $0.015 |
| CL.c.0–c.11 curve daily OHLCV, 5 yr | $0.18 |
| CL.c.0–c.5 curve daily OHLCV, 10 yr | $0.18 |
| CL.c.0 hourly OHLCV, 5 yr | $0.29 |
| BRN.c.0 daily OHLCV, 5 yr | $0.39 |
| HO + RB daily OHLCV, 5 yr | $0.03 |
| CL + HO + RB + NG daily OHLCV, 5 yr | ~$0.10 |
| CL.c.0 BBO-1m (bid-ask spread), 2 yr | $0.91 |
| CL.c.0 OHLCV-1m, 1 yr | $1.20 |
| CL.c.0 MBP-1 (full order book), 1 yr | $64.49 |

**Practical budget for an ML training dataset covering all signals below: ~$2–3 total.**

## ML signal map for `WTI_FRONT_1W_LOG_RETURN`

The following signals are directly constructable from Databento data and map to existing desk hypotheses:

### `storage_curve` desk (term structure / roll yield)
- **1-month roll yield**: `(CL.c.0 − CL.c.1) / CL.c.1` — direct measure of storage economics; negative = contango = storage full/bearish
- **Curve slope (1M→12M)**: `(CL.c.0 − CL.c.11) / CL.c.11` — full backwardation/contango regime
- **Belly curvature**: `CL.c.3 − 0.5*(CL.c.1 + CL.c.5)` — storage arbitrage signal in mid-curve
- **Calendar spread momentum**: rolling ∆ in roll yield (momentum of storage signal)
- Historical depth: 2010 → present (~14 years) on daily, 2017 → present on MBO

### `oil_demand_nowcast` desk (demand + macro alpha)
- **3-2-1 crack spread**: `(2×RB.c.0 + HO.c.0 − 3×CL.c.0) / 3` — refinery margin; high = strong product demand
- **Gasoline crack**: `RB.c.0 − CL.c.0` — US transportation demand
- **Distillate crack**: `HO.c.0 − CL.c.0` — industrial/heating demand
- **Intraday volume profile**: hourly OHLCV for session-level demand signal
- **BBO queue depth**: `bid_sz_00 + ask_sz_00` from bbo-1m — thin books → demand uncertainty

### `supply_disruption_news` desk (supply + geopolitics)
- **Brent-WTI spread**: `BRN.c.0 − CL.c.0` — grade differential; widens on Middle East supply risk
- **Brent curve structure**: `BRN.c.0 − BRN.c.2` — Brent backwardation independent of WTI
- **Prompt premium**: `CL.c.0 − CL.c.2` normalised by price — spot supply tightness signal

### Cross-asset / `regime_classifier`
- **Energy complex co-movement**: NG.c.0 returns alongside CL.c.0 — gas-to-oil substitution regimes
- **Oil-equity vol regime**: pair with VIX from equity sim (already in system) — risk-on/risk-off switching

## Recommended fetch targets for initial ML training

```python
SYMBOLS_DAILY = {
    'GLBX.MDP3': [
        'CL.c.0', 'CL.c.1', 'CL.c.2', 'CL.c.3', 'CL.c.4', 'CL.c.5',
        'CL.c.6', 'CL.c.7', 'CL.c.8', 'CL.c.9', 'CL.c.10', 'CL.c.11',
        'HO.c.0', 'HO.c.1',
        'RB.c.0', 'RB.c.1',
        'NG.c.0', 'NG.c.1',
    ],
    'IFEU.IMPACT': ['BRN.c.0', 'BRN.c.1', 'BRN.c.2'],
}
SCHEMA = 'ohlcv-1d'
START = '2019-01-01'   # 5yr common window covers IFEU history; extend to 2014 for GLBX-only
END = '2026-05-14'
# Estimated cost: ~$0.50 total
```

For microstructure / intraday features add `bbo-1m` for `CL.c.0` from 2022 (~$0.90).

## Limitations and notes

1. **MBO/tick data is expensive** ($64/yr for full order book). Avoid for ML training unless microstructure research is specifically in scope.
2. **Open Interest from `statistics` schema** has a data quirk: `quantity` field overflows int32 for large OI values. The `price` field carries the actual OI level.
3. **Brent continuous symbol is `BRN.c.0`** (not `B.c.0` or `CO.c.0`). `B.c.0` resolves but maps to nothing for IFEU.IMPACT.
4. **IFEU starts 2018-12-23** so Brent-WTI spread history is limited to ~7 years vs 14 for WTI-only signals.
5. **Dirty-tree / production mode**: per `bus/` production-mode constraint, fetched data should be pinned to a specific date range with a hash so replay is byte-identical (§4.3 provenance).
