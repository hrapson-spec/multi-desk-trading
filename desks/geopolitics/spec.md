# Geopolitics & Risk Desk — Spec

**Phase**: 1 (deepen Week 4).
**Status**: Week 1-2 stub only.

## 1. Target variables and horizons

- `wti_front_month_close` @ EventHorizon(eia_wpsr, ~7d) — event-premium overlay.
- Additional targets (per-event probability, per-event barrel impact) added via v1.x registry.

## 2. Directional claim

**Positive** on `wti_front_month_close` wrt `event_barrel_impact_probability`.

Stub: sign = "none".

## 3. Pre-registered naive baseline

Caldara-Iacoviello GPR daily index as a single-feature regression baseline.

## 4. Model ladder

1. Zero-shot: Local Qwen-2.5-7B Q4 via MLX for high-volume news extraction; Claude/GPT API for contested-event reasoning (bullish/bearish/neutral debate triad per §4 of the original proposal).
2. Classical specialist: Bayesian event-impact regression with expert priors; historical-analogue matching.
3. Fine-tune: N/A at this scale (LLM domain).

## 5. Gate-pass plan

- **Gate 1 (skill)**: Beat GPR-alone regression on test-period `wti_front_month_close` RMSE.
- **Gate 2 (sign preservation)**: Spearman(signed event-impact, forward realised vol) positive on dev and test.
- **Gate 3 (hot-swap)**: Replaceable by StubDesk.

Calibration: public evaluation log of event probabilities vs outcomes; Brier score reported weekly.

## 6. Data sources

- Reuters web scrape (rate-limited)
- AP / Regional RSS feeds (Middle East focus)
- OFAC / HMT / EU sanctions downloads (public)
- Caldara-Iacoviello GPR (Fed website, daily)

All free / public.

## 7. Internal architecture

Multi-agent debate for contested events (bull/bear/neutral triad); single-agent extraction for uncontested. Output JSON schema with probability, time-horizon, barrel-impact, sources-cited fields.

## 8. Capability-claim debits

- **Pre-emptive**: LLM look-ahead bias (Glasserman-Lin 2023). Every backtest uses an LLM whose training cutoff predates the test window.
