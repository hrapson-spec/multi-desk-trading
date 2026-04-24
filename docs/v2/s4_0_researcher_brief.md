# S4-0 external researcher brief

- **Status**: fulfilled by `s4_0_research_findings.md`
- **Created**: 2026-04-24
- **Stage**: S4-0 recorded replay
- **Owner**: Henri Rapson

## 1. Research Objective

Define the external data, licensing, and operational evidence requirements for
a no-money S4-0 recorded replay rehearsal of the WTI / oil family.

The researcher should not assess whether the trading strategy is profitable.
The assignment is to identify what a credible no-capital operational rehearsal
must prove, which recorded replay data sources are viable, and which licensing
or evidence constraints could block the run.

## 2. Target Scope

Initial scope:

- NYMEX WTI crude oil futures.
- CL front-month contract.
- CL next-month contract.
- Contract-roll handling as an explicit test area.
- Recorded replay first.
- One full trading session first, then one trading week if clean.

Do not expand to Brent, refined products, ETFs, or broad macro/oil instruments
unless listed as future-scope options.

## 3. Data Sources To Compare

Compare candidate sources without assuming a winner:

- CME official data / CME DataMine.
- Databento CME Globex MDP 3.0.
- dxFeed futures / market replay.
- Barchart market replay or historical futures data.
- LSEG tick history or CME data products, if institutional-grade audit
  evidence is needed.

For each candidate, compare:

| Dimension | Required notes |
|---|---|
| Dataset coverage | CL front-month, next-month, historical depth, contract metadata. |
| Replay feasibility | API or file format, reproducible replay, speed control, local replay support. |
| Timestamp quality | Exchange timestamp, receive timestamp, sequencing, timezone semantics. |
| Data quality controls | Gap flags, corrections, duplicates, session definitions. |
| Access model | API, batch download, hosted replay, account entitlement. |
| Cost shape | Trial, monthly, per-dataset, per-user, per-exchange, redistribution fees if known. |
| Licence boundary | Non-display use, local storage, replay, retention, reviewer access. |
| Audit usefulness | Ability to preserve raw inputs and prove what was replayed. |

## 4. Licence Hard Gate

No source may be recommended for S4-0 unless the licence position is clear on:

- Non-display use.
- Local storage.
- Local replay.
- Retention duration.
- Use in internal audit/review.
- Whether an external reviewer can inspect evidence.
- Restrictions on publishing or sharing derived results.

If the researcher cannot determine any item, mark it as unresolved rather than
assuming permission.

## 5. Operational Standards Research

Summarize external best practice for shadow-live or pre-production trading
system validation. Focus on controls rather than performance claims:

- Declared run windows.
- Uptime and monitoring.
- Feed gap and duplicate handling.
- Timestamp and sequencing validation.
- Reference-data and contract-roll checks.
- Order/execution simulation controls.
- Incident records.
- Alerting and manual override records.
- Replayability.
- Restore/recovery drills.
- Reconciliation from raw input to ledger.
- Pre-registered stop/go criteria.

## 6. Failure Modes To Cover

Produce a risk register covering at least:

- Bad timestamps.
- Missing ticks or bars.
- Duplicate data.
- Feed delays.
- Wrong contract roll.
- Stale features.
- Simulator drift.
- Clock skew.
- Silent abstentions.
- Alerting gaps.
- Operator mistakes.
- Licence or entitlement misunderstanding.

For each risk, include detection method, mitigation, severity, and whether it
is a hard blocker for S4-0.

## 7. Required Deliverables

Return:

- 10-15 page written memo.
- Source links for every factual claim.
- Vendor/data-source comparison table.
- Licence boundary table.
- Proposed S4-0 run checklist.
- Proposed evidence-pack checklist.
- Risk register.
- Top 10 open owner decisions.
- Clear separation of facts, assumptions, and recommendations.

## 8. Decision Output Needed

The final recommendation must state:

- Whether S4-0 should use one of the candidate sources.
- Which data source is preferred and why.
- Which licence questions remain unresolved.
- Which session window and contract pair are suitable for the first rehearsal.
- Whether the evidence expected by `s4_0_evidence_manifest.md` is feasible with
  the recommended source.
