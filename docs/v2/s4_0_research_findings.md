# S4-0 external research findings

- **Status**: research received, tag `v2-s4-0-research-0.1`
- **Created**: 2026-04-24
- **Stage**: S4-0 recorded replay
- **Source**: external researcher memo supplied by owner
- **Scope**: NYMEX WTI crude oil futures, CL front-month and next-month, recorded replay first

## 1. Executive Finding

The external research output recommends Databento CME Globex MDP 3.0 as the
preferred technical data path for the first S4-0 recorded replay rehearsal,
conditional on written licence confirmation.

The recommendation is conditional because the remaining blocker is licensing,
not technical feasibility. S4-0 must not start until the licence position is
clear for non-display use, local storage, local replay, retention, internal
review, external reviewer access if needed, and derived-output handling.

This document records the decision-relevant findings. It is not legal advice.

## 2. Candidate Ranking

| Rank | Candidate | Research view |
|---|---|---|
| 1 | Databento CME Globex MDP 3.0 | Best conditional technical fit for S4-0 recorded replay. Licence must be confirmed. |
| 2 | dxFeed futures / Market Replay | Strong replay-focused alternative. Contract terms and pricing less transparent publicly. |
| 3 | CME official data / CME DataMine | Best official provenance. Potentially heavier licensing/procurement and less convenient replay ergonomics. |
| 4 | LSEG Tick History / PCAP | High institutional audit quality, likely overbuilt for the first one-session rehearsal. |
| 5 | Barchart Market Replay / historical futures data | Viable lower-friction candidate, but weaker public evidence on timestamp depth and audit-grade controls. |

## 3. Conditional Source Decision

| Decision area | Current position |
|---|---|
| Preferred technical candidate | Databento CME Globex MDP 3.0 |
| Approval status | Conditional only |
| Reason | Best balance of CME/NYMEX coverage, historical/live schema continuity, replay practicality, timestamp semantics, and local evidence fit. |
| Hard blocker | Written licence clearance is not yet obtained. |
| Fallback candidates | dxFeed, CME DataMine, LSEG Tick History, Barchart. |

## 4. Recommended First Rehearsal

| Area | Recommendation |
|---|---|
| Data mode | Recorded replay |
| Instruments | CL front-month and CL next-month |
| Candidate pair around 2026-04-24 | CLM6 / CLN6, subject to immediate pre-run confirmation |
| Session type | Ordinary non-expiry, non-roll, non-holiday full trading session |
| Stress events | Avoid deliberate EIA release, expiry, or roll stress for the first rehearsal |
| Replay speed | 1x first; accelerated replay only after evidence chain works |
| Expansion condition | One trading week only after the first session is clean |

The CL contract pair must be confirmed immediately before execution using CME
expiry resources or the chosen vendor's contract metadata. It must not be
assumed from planning-date context alone.

## 5. Licence Hard Gates

S4-0 cannot execute until written confirmation covers:

- Automated non-display use.
- Local storage of raw replay data.
- Local replay.
- Retention period.
- Internal audit/review.
- External reviewer access, if needed.
- Whether raw data, normalized data, derived data, screenshots, checksums, and
  replay outputs can be included in the evidence pack.
- Whether derived summaries or charts can be shown outside the licensed
  environment.

If raw-data sharing with an external reviewer is not permitted, S4-0 may still
proceed only under a restricted reviewer model where the reviewer inspects
checksums, manifests, redacted receipts, and replay outputs inside the licensed
environment.

## 6. Execution Blockers

The research output identifies these as blockers before S4-0 start:

- Unclear non-display rights.
- Unclear local storage rights.
- Unclear local replay rights.
- No proof that CL front and next contracts are available.
- No way to preserve a replayable data manifest.
- No no-money attestation.
- No timestamp semantics.
- No receipt schema.
- No incident register.
- No stop/go criteria.

## 7. One-Week Expansion Blockers

The first one-session rehearsal may still be amber, but one-week expansion
should wait if any of these remain unresolved:

- External reviewer access unresolved.
- Restore documented but not tested.
- Alerting partially tested but not robust.
- No secondary reconciliation source.
- Minor explained replay divergence.
- Minor explained data gaps.
- Manual roll/contract checks not yet automated.
- Simulator assumptions documented but not independently reviewed.

## 8. Owner Decisions Remaining

| Decision | Current recommendation |
|---|---|
| Primary source | Choose Databento conditionally; keep alternatives open. |
| Licence route | Require written confirmation from vendor and, where applicable, exchange licence route. |
| Reviewer model | Start with internal reviewer; design restricted external review if raw data cannot be shared. |
| Market depth | Use the minimum depth required by features and simulator; prefer MBP-10 or MBO if execution simulation needs book context. |
| First session date | Use ordinary non-expiry, non-roll, non-holiday session. |
| Contract pair | Use front/next from CME expiry calendar or vendor metadata; planning candidate is CLM6/CLN6 around 2026-04-24. |
| Replay speed | Use 1x first. |
| Simulator scope | Include documented simulator assumptions; do not overclaim execution realism. |
| Restore requirement | Document in first session; test before one-week expansion. |
| Pass/fail authority | Owner plus technical reviewer for first session; add legal/compliance input before one-week expansion or external sharing. |

## 9. Decision Output

The research commission is complete. S4-0 is not yet execution-ready.

Next required action: obtain written Databento/CME licence clearance or record a
source-selection blocker and move to an alternate candidate.
