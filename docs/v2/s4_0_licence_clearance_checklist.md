# S4-0 licence clearance checklist

- **Status**: required before execution
- **Created**: 2026-04-24
- **Stage**: S4-0 recorded replay
- **Preferred technical candidate**: Databento CME Globex MDP 3.0
- **Related finding**: `s4_0_research_findings.md`

## 1. Purpose

This checklist converts the external research output into the written
clearance needed before S4-0 can execute. It is not legal advice. It defines
the questions that must be answered by the vendor, exchange licence route, or
legal/compliance reviewer.

## 2. Required Written Answers

| Question | Required answer before S4-0 |
|---|---|
| Does the licence permit automated non-display use for an internal no-money recorded replay system? | Yes / no / restricted terms. |
| Does the licence permit local storage of raw Databento/CME replay data? | Yes / no / retention limit. |
| Does the licence permit local replay from stored files or API extracts? | Yes / no / restricted method. |
| What retention period is allowed for raw data, normalized data, receipts, logs, and derived outputs? | Explicit duration by evidence type. |
| Can an internal reviewer inspect raw market data and derived evidence? | Yes / no / user-entitlement constraints. |
| Can an external reviewer inspect raw market data? | Yes / no / restricted model / additional licence required. |
| If raw data cannot be shared externally, can a reviewer inspect manifests, hashes, redacted receipts, and replay outputs inside the licensed environment? | Yes / no / conditions. |
| Can normalized data be retained as part of the evidence pack? | Yes / no / retention limit. |
| Can derived data, including features, forecasts, decision receipts, simulated orders, fills, ledgers, summaries, and charts, be retained? | Yes / no / restrictions. |
| Can derived summaries or charts be shown outside the licensed environment? | Yes / no / restrictions. |
| Can screenshots or sample excerpts be included in internal evidence? | Yes / no / restrictions. |
| Can checksums and file manifests be retained indefinitely? | Yes / no / restrictions. |
| Does buying via Databento satisfy all CME/NYMEX requirements for this use, or is a direct CME non-display licence also required? | Explicit route. |
| Are there reporting obligations for this recorded replay/non-display usage? | Yes / no / reporting frequency. |
| Are there exchange, per-user, per-application, or reviewer fees triggered by the S4-0 design? | Explicit fee trigger summary. |

## 3. Evidence To File

Store clearance evidence under the eventual S4-0 evidence root:

```text
evidence/s4_0/<run_id>/01_entitlements/
```

Minimum files:

- `licence_boundary_table.md`
- `vendor_terms_summary.md`
- `exchange_route_summary.md`
- `reviewer_access_model.md`
- `unresolved_licence_questions.md`
- `owner_clearance_decision.md`

Do not store secrets, API keys, or full confidential agreements in the repo.
Use references, excerpts, or local evidence paths where needed.

## 4. Stop Condition

If any of these remain unclear, S4-0 does not start:

- Non-display rights.
- Local storage rights.
- Local replay rights.
- Retention rights.
- Internal review rights.
- Whether external reviewer access is allowed or must be restricted.
- Whether derived evidence can be retained and summarized.
