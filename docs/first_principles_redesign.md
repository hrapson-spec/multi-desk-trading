# First-Principles Redesign of Underperforming Desks

**Status**: Adopted external review. Supersedes earlier in-progress first-principles content (never committed).
**Date**: 2026-04-22
**Scope**: desk decomposition, target identifiability, observability, simulator realism, evaluation framing.
**Out of scope**: `contracts/`, `controller/`, `bus/`, `persistence/`, `eval/hot_swap.py`, `provenance/`, `scheduler/` (all frozen per `docs/architecture_spec_v1.md` §§4, 6-11).

---

## Project constraint binding every recommendation

`controller/decision.py:94-112` computes `combined_signal = Σ weight × point_estimate` over all `(desk, target)` rows in the regime weight table. Mixed-unit targets (prompt-spread change, deferred-strip residual, realized-vol surprise, IV/skew delta) cannot be summed cleanly under this rule. **Each desk family therefore emits one shared decision-space unit**:

- Oil family: `WTI_FRONT_1W_LOG_RETURN` (signed 1-week log return).
- Equity-VRP family: `VIX_30D_FORWARD_3D_DELTA` (signed 3-day vol delta; added to `contracts/target_variables.py` at v1.16).

Per-desk alpha targets below are **internal/auxiliary labels only**, never emitted.

---

## Executive call

| Current desk | Verdict | Why |
|---|---|---|
| Oil `supply` | Keep, redesign, merge with geopolitics | Fast supply shocks are event/news mechanisms; current desk mixes slow supply response with fast disruption news. |
| Oil `demand` | Keep, redesign, absorb most of macro | The real desk is oil-demand / global-activity nowcasting, not generic macro. |
| Oil `geopolitics` | Remove as standalone; absorb into `supply_disruption_news` | Geopolitics is not a separable continuous desk here; it is a source of supply-risk / precautionary-demand events. |
| Oil `macro` | Remove as standalone alpha desk | Mostly a regime/conditioning layer or macro-release event effect, not a stable direct oil forecaster in this architecture. |
| Equity VRP `dealer_inventory` | Keep, rename/re-scope | What is identifiable is not true dealer inventory but surface positioning feedback. |
| Equity VRP `hedging_demand` | Keep only if signed flow exists; else merge/remove | Without signed customer/dealer flow, this is not separately identifiable from positioning / surface state. |

## Adopted decomposition

### Oil (3 desks, down from 5)

1. **`storage_curve`** — unchanged.
2. **`supply_disruption_news`** — absorbs current `supply` fast component + `geopolitics`. Event-hurdle model: activation probability × conditional effect size. Emits near-zero outside activated states.
3. **`oil_demand_nowcast`** — absorbs current `demand` + most of `macro` (alpha part). Mixed-frequency state-space / dynamic-factor nowcast.

Optional later: `slow_supply_response` — only if simulator/data can support 20–60d production/capacity response (Phase 3 deferred).

### Equity VRP (1 shipped desk merged; scale-out roster rebalanced)

- **`surface_positioning_feedback`** (renamed + merged `dealer_inventory` + `hedging_demand`). Under the current public-data and frozen-controller constraints, the two-desk split is not identifiable.
- Conditional future split, **only if richer observables arrive**:
  - `dealer_inventory_pressure` — for true dealer gamma / vega warehousing.
  - `customer_flow_pressure` — for customer downside demand and skew pressure.
- Keep **`earnings_calendar`** separate (planned Phase 2 scale-out); otherwise it contaminates flow-pressure signal.
- **`macro_regime`** (planned Phase 2 scale-out): DROPPED as standalone alpha desk; demoted to conditioning/context via `regime_classifier`.
- **`term_structure`** (planned Phase 2 scale-out): review is silent; DEFERRED pending re-check.

---

## Desk-by-desk review

### 1. Oil supply → keep, redesign, merge with geopolitics as `supply_disruption_news`

**Mechanism map.** OPEC / outage / sanctions / weather / shipping disruption news → expected near-term flow shortfall → tighter prompt balance / higher convenience yield → prompt spread widens, front strip reprices.

**Observability audit.**
- *Green*: timestamped OPEC decisions, outage notices, pipeline/shipping disruptions, spare-capacity proxies, official release calendars.
- *Amber*: rig counts, capex, monthly production estimates, tanker loadings.
- *Red*: latent political intent, hidden spare capacity, generic "sentiment" standing in for physical news.

**Mechanism actually being captured.** Exogenous or announced changes in expected near-term physical supply, not generic "supply fundamentals."

**Right target / horizon?** Usually no if the current target is outright oil level/return. **Better internal target**: 1–5 day change in prompt calendar spread (e.g. M1–M3 or M1–M6), or front-strip residual after removing `storage_curve`. **Controller-facing emission**: `WTI_FRONT_1W_LOG_RETURN` (auxiliary labels: `p_disruption`, `signed_barrel_impact`, `planned_supply_surprise_z`).

**Does the current simulator / observation layer encode it strongly enough?** Probably not unless it has explicit event states and release timing. If supply shock is just another smooth latent factor, no model class will recover the right short-horizon behavior.

**Separable from neighbors?** Not from geopolitics on short horizons. Separable from `storage_curve` only if internally targeting the residual move before inventories fully absorb the shock.

**Minimally sufficient model family.** Two-stage hurdle/event model: activation probability × conditional effect size. Small Bayesian event-study model or boosted trees on structured event features, not a generic ridge on summary features.

**Most likely failure mode.** Desk design + simulator design. A sparse event mechanism has been framed as a dense continuous regression problem.

**Fast falsification.** In the simulator, intervene on supply-news shocks while holding other mechanisms fixed. If prompt spreads do not respond monotonically and observables do not light up at decision time, kill the desk or redesign the simulator first.

### 2. Oil demand → keep, redesign, absorb most of macro as `oil_demand_nowcast`

**Mechanism map.** Global activity / refinery demand / product demand nowcast → higher expected call on crude → deferred strip reprices first, then inventories tighten.

**Observability audit.**
- *Green*: as-of PMIs, refinery margins/cracks, refinery runs/utilization, freight/shipping proxies, product-demand proxies, import/export data, release calendar.
- *Amber*: mobility/alt-data nowcasts, Chinese activity proxies, industrial-production nowcasts.
- *Red*: revised macro data not yet published, final demand balances, hindsight monthly revisions.

**Mechanism actually being captured.** Oil-demand / global-activity nowcasting, not generic macro forecasting.

**Right target / horizon?** Better internal target: 5–20 day change in deferred strip or strip-average residual. **Controller-facing emission**: `WTI_FRONT_1W_LOG_RETURN` (auxiliary: `physical_demand_surprise_z`, `refinery_run_surprise_z`).

**Does the simulator encode it strongly enough?** Only if it models publication lags, revisions, and mixed-frequency releases. A smooth macro latent without release mechanics is too weak and too unrealistic.

**Separable from neighbors?** Separable from `storage_curve` if targeted to the deferred strip. Not cleanly separable from current macro — most of current macro belongs here.

**Minimally sufficient model family.** Mixed-frequency state-space / dynamic-factor nowcast is the minimum. One of the few places where a multivariate covariate model is justified.

**Failure mode.** Desk design + train/serve boundary + simulator design. The desk probably claims faster, cleaner signal than the real information set allows.

**Fast falsification.** Train a simple Kalman-style demand nowcast on as-of releases. If even that cannot beat a naive baseline on the proposed target, the simulator is not encoding the mechanism, or the desk should be retired.

### 3. Oil geopolitics → remove as standalone; absorb into `supply_disruption_news`

**Mechanism map.** Conflict / sanctions / choke-point risk / OPEC rhetoric → higher probability of future disruption or precautionary hoarding → prompt spread widens, regional dislocations, vol rises.

**Observability audit.**
- *Green*: structured event feed with timestamps and categories.
- *Amber*: curated news tags, sanctions databases, shipping chokepoint alerts.
- *Red*: generic sentiment scores, latent "geopolitical tension" factor with no causal path.

**Mechanism actually being captured.** Not a standalone continuous factor. A source of supply-news shock and sometimes precautionary-demand shock.

**Right target / horizon?** Not as a daily level forecaster. If reintroduced, would be an event-jump / spread-risk classifier over 0–5 days.

**Recommendation.** Remove as standalone now. Absorb into `supply_disruption_news`. Reintroduce later only if structured event channels and, ideally, regional spread targets are added.

**Expected Gate 1 / Gate 2 after redesign.** No standalone gate. Improvement should show up in merged `supply_disruption_news`.

### 4. Oil macro → remove as standalone alpha desk

**Mechanism map.** Growth / dollar / real-rate / inflation shock → changes in oil-demand expectations and commodity risk premium → deferred strip / cross-asset beta move.

**Observability audit.**
- *Green*: timestamped macro-release surprises, DXY, real yields, breakevens, equities, credit.
- *Amber*: growth nowcasts, policy path probabilities.
- *Red*: revised macro states or ex post narratives.

**Mechanism actually being captured.** Cross-asset macro conditioning, not a clean oil-specific desk.

**Recommendation.** Remove as a standalone oil desk. Use macro only as a conditioning layer inside `oil_demand_nowcast` and `supply_disruption_news`, or later reintroduce a tiny `macro_release_shock` desk if the simulator earns it. Primary conditioning happens via §10 `regime_classifier` (HMM regime state).

**Expected Gate 1 / Gate 2 after redesign.** No standalone gate. Neighbor desks should improve once macro is treated as context instead of forced decomposition.

### 5. Equity VRP `dealer_inventory` → keep, rename to `surface_positioning_feedback`

**Mechanism map.** Aggregate option positioning (gamma/vanna/charm, especially short-dated) × spot move → dealer hedging feedback → next-session realized variance surprise and mean-reversion / momentum regime.

**Observability audit.**
- *Green*: previous-day open interest, current-day volume, full option chain by strike/maturity, estimated greeks, spot distance to large strikes, liquidity, event calendar.
- *Amber*: model-based aggregate GEX/VEX/CEX proxies from OI assumptions.
- *Red*: true dealer book, same-day final OI at close, inferred customer/dealer attribution without flow data.

**Mechanism actually being captured.** Not true dealer inventory. What is observable is market-wide surface positioning and its feedback effects.

**Right target / horizon?** Better internal target: next-session realized vol surprise relative to implied / fair-vol baseline, or a compression / neutral / amplification classifier. **Controller-facing emission**: `VIX_30D_FORWARD_3D_DELTA` (new v1.16 target). Internal auxiliary: `next_session_rv_surprise` (requires a decision-time `fair_vol_baseline` channel — added at C11 of the restructure plan as a trailing-k-day vol mean with explicit lag).

**Does the current simulator / observation layer encode it strongly enough?** Only if it has a real options-surface state and a hedge-feedback loop. Summarized feature vectors are unlikely to be enough. Current `sim_equity_vrp/` is a 4-factor AR(1) latent system — a placeholder for the architecture claim, not a full surface model.

**Separable from neighbors?** Separable from the (former) `hedging_demand` only if this desk is defined on the realized side and the other on the implied side, and only if signed flow exists for the latter. Under current data, merge.

**Minimally sufficient model family.** Monotone GAM / boosted-tree classifier with regime conditioning. Low-dimensional nonlinear mechanism, not necessarily a deep-learning problem.

**Failure mode.** Desk design + simulator design. The desk likely targets the wrong horizon and overclaims observability.

**Fast falsification.** Check monotonicity: do positive-positioning states predict lower next-session realized-vol surprise, after conditioning on scheduled events and baseline IV/HAR-RV? If not, either the simulator feedback loop is weak or the proxy is invalid.

### 6. Equity VRP `hedging_demand` → merge/remove (no signed flow available)

**Mechanism map.** Customer demand for protection/convexity → dealer intermediation and repricing → implied vol/skew richens or cheapens → VRP wedge changes, with later decay or normalization.

**Observability audit.**
- *Green*: signed customer/dealer buy-sell open-close flow by strike/maturity, event calendar, ETF/fund flow proxies, same-day volume.
- *Amber*: previous-day OI changes, put/call ratios, surface state proxies.
- *Red*: "hedging demand" inferred only from price or same-day final OI.

**Mechanism actually being captured.** Customer flow pressure on the implied side of the market, not future realized variance directly.

**Separable from neighbors?** Not from `dealer_inventory` if both are inferred from the same EOD surface summaries. Becomes separable only if this desk owns the implied-price-pressure claim and `surface_positioning_feedback` owns the realized-feedback claim — which requires signed flow.

**Current sim state.** `sim_equity_vrp/latent_state.py` has no signed flow channels; `put_skew_proxy = hedging_demand × vol_level` is signed-by-construction (not ≥ 0). The pasted review's rule applies: **without signed flow, do not keep this standalone**. Merge weak proxies into `surface_positioning_feedback`.

**Failure mode.** Primarily observability failure. Secondarily train/serve boundary (OCC states OI is derived from previous-day settlement, so using same-day final OI as a close-time input is illegitimate).

**Future reintroduction.** If signed flow arrives in a later simulator revision (Phase 3), split back into `customer_flow_pressure` targeting 1–5 day change in short-dated IV / skew / VRP wedge.

---

## Concrete redesign spec

| New desk | Internal target | Horizon | Features | Model family | Calibration |
|---|---|---|---|---|---|
| `supply_disruption_news` | Δ(prompt spread) or front-strip residual vs `storage_curve` | 1–5d | OPEC/outage/sanctions/shipping events, spare-cap proxies, curve state | Hurdle event model; Bayesian event study / GBDT | Activation prob × conditional move size; neutral outside active states |
| `oil_demand_nowcast` | Deferred-strip residual (e.g. ΔF₆ₘ or strip-avg residual) | 5–20d | vintaged PMIs, refinery/product data, cracks, freight, import/export, release calendar | Mixed-frequency state-space / dynamic factor | Regime-specific isotonic on signed residual move |
| `surface_positioning_feedback` | Next-session realized-vol surprise or {compress, neutral, amplify} class | 1d | full surface, prior OI, current volume, GEX/VEX/CEX proxies, strike concentration, event calendar, liquidity | Monotone GAM / GBDT classifier | 3-class probability calibration; confidence shrinkage on event days |
| `customer_flow_pressure` (Phase 3, conditional on signed flow) | 1–5d change in front IV/skew/VRP wedge | 1–5d | signed customer/dealer flow, participant type, open/close buy-sell, event calendar, surface state | Small state-space / GBDT | Probability of richen/cheapen × expected magnitude |

**Controller-facing emission is fixed**: `WTI_FRONT_1W_LOG_RETURN` (oil family) or `VIX_30D_FORWARD_3D_DELTA` (equity family). The column above is the INTERNAL label only.

---

## Required simulator / data changes

### Oil

- Separate fast supply-news shocks from slow production-response shocks.
- Add timestamped event channels: OPEC meetings, quota surprises, outages, sanctions, hurricanes, SPR announcements.
- Add mixed-frequency release mechanics for demand and macro: publication lags, revisions, as-of vintages.
- Emit curve states by maturity, not just a compressed price summary.
- Allow simulator latent shock tags to be used as auxiliary training labels only, never serve-time inputs.

### Equity VRP

- Preserve the full option surface by strike and maturity, or at least richer maturity buckets plus concentration metrics.
- Enforce the OI timing boundary correctly (prior-day settlement, not same-day close).
- Add signed option flow / participant-type flow if `customer_flow_pressure` is to exist (Phase 3 prerequisite).
- Add a hedge-feedback mechanism linking surface positioning to realized-vol / path behavior.
- Add scheduled-event channels so earnings/macro do not masquerade as generic hedging demand.
- Add decision-time `fair_vol_baseline` channel (trailing k-day vol mean with explicit lag) to support `surface_positioning_feedback` internal surprise label.

---

## Minimal experiment plan

1. **Interventional identifiability sweep.** In the simulator, shock one latent mechanism at a time and verify: observable channel moves → proposed internal target moves → neighboring desks do not respond the same way.
2. **Target/horizon bake-off before model bake-off.** For each desk, compare 3–4 candidate internal targets/horizons with a tiny model first. If the target is wrong, no model family will save it.
3. **Train/serve boundary audit.** Rebuild features as true as-of snapshots. Critical for macro vintages and option OI timing.
4. **Low-capacity falsification first.** If a simple state-space / event-study / monotone tree cannot find stable signal, do not move to a foundation model.
5. **Conditional-sample evaluation.** For sparse desks, inspect active-window skill separately from unconditional averages. Desk should emit neutral forecasts outside activation, but operator needs to know where the edge lives.
6. **Negative controls.** Permute event timestamps, flow signs, or maturity labels. Real mechanism desks should collapse under these perturbations.

---

## Migration plan by payoff vs cost

### Very high payoff / low cost (Tier 1)

1. Remove standalone `geopolitics` and `macro`. Merge them into better-defined desks.
2. Re-target `dealer_inventory` to next-session realized-vol surprise; rename `surface_positioning_feedback`.
3. Audit the train/serve boundary for macro vintages and options OI timing.

### High payoff / medium cost (Tier 2)

4. Rebuild oil into `supply_disruption_news` + `oil_demand_nowcast` with structured event + nowcast pipelines.
5. Add event channels to oil sim; add mixed-frequency release mechanics.
6. Add richer equity surface state to `sim_equity_vrp/`.

### Very high payoff / high cost (Tier 3, Phase 3)

7. Add signed option-flow / participant-type flow so `customer_flow_pressure` can exist honestly.
8. Build a first-principles oil simulator (balance, event shocks, cross-asset) separate from the AR(1) architecture smoke test.
9. Only after the above, benchmark foundation-model challengers (ChronosX, Moirai, TimesFM) as challengers, not first fixes.

---

## AI model recommendations

Foundation models are challengers **after** desk claims are fixed, not before.

- `oil_demand_nowcast`: Chronos-2 or ChronosX as a challenger to the state-space nowcast (once mixed-frequency releases exist in the sim).
- `surface_positioning_feedback`: Kronos or Chronos-2 as a challenger on richer market-state histories.
- `customer_flow_pressure`: not first choice; signed flow + a simpler structured model is more appropriate.

**Where AI models do not help.** They will not fix missing observability. No model can infer true dealer books, same-day final OI, or structured supply news if the observation layer does not expose them.

---

## Bottom line

- Oil: keep `storage_curve`; replace `supply` + `geopolitics` with `supply_disruption_news`; replace `demand` + most of `macro` with `oil_demand_nowcast`; remove standalone `macro`.
- Equity VRP: keep `dealer_inventory` renamed as `surface_positioning_feedback`; merge `hedging_demand` into it under current no-signed-flow regime; keep `earnings_calendar` planned; drop `macro_regime`; defer `term_structure`.
- The first win is not a bigger model. The first win is making each desk forecast a mechanism that is actually identifiable from the information available at decision time.
