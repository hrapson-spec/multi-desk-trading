# Demand Desk — Spec

**Phase**: 1 (deepen Week 5-10 parallel with Supply).
**Status**: Week 1-2 stub only.

## 1. Target variables and horizons

- `wti_front_month_close` @ EventHorizon(eia_wpsr, ~7d)
- Implied inventory-draw = forecast supply path − forecast demand path (feeds Storage & Curve).

## 2. Directional claim

**Negative** on `wti_front_month_close` wrt `demand_weakness_z` (weaker demand → lower forward price).

Stub: sign = "none".

## 3. Pre-registered naive baseline

Persistence: last IEA-reported global demand YoY growth.

## 4. Model ladder

1. Zero-shot: TabPFN-v2 for cross-sectional (activity × oil intensity) relationships; BSTS + horseshoe prior for nowcasting.
2. Classical specialist: CatBoost on refining margins → run rates; mixed-frequency BVAR (Cimadomo 2022) for activity path.
3. Fine-tune: only if both fail.

## 5. Gate-pass plan

- **Gate 1**: Beat last-print persistence on IEA monthly runs RMSE.
- **Gate 2**: Positive dev/test Spearman on signed demand-residual vs forward realised vol.
- **Gate 3**: Hot-swap against StubDesk.

## 6. Data sources

- IEA OMR (monthly oil market report)
- JODI demand-side
- Google Trends (transport fuel search proxies)
- China customs, teapot utilisation (free scraped)
- PMI global composites
- Port throughput / road traffic (free proxies)

## 7. Internal architecture

TBD.

## 8. Capability-claim debits

None at stub phase.
