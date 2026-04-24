# S4-0 external research findings

- **Status**: archived commercial-data research
- **Created**: 2026-04-24
- **Superseded**: 2026-04-24 by local/free S4-0 scope decision
- **Stage**: S4-0 recorded replay
- **Source**: external researcher memo supplied by owner

## 1. Current Decision

The Databento/CME licensed-data route is no longer a requirement for S4-0.
S4-0 may execute and be assessed using local/free or synthetic recorded replay
data, provided the evidence pack records source limitations and makes no claims
about profitability, live execution quality, licensed-feed handling, or real
market readiness.

## 2. What Remains Useful

The research remains useful as optional future context for commercial-data
upgrades:

| Candidate | Archived view |
|---|---|
| Databento CME Globex MDP 3.0 | Strong engineering candidate if commercial CL data is later purchased. |
| dxFeed futures / Market Replay | Replay-focused alternative if hosted replay controls matter later. |
| CME DataMine | Official provenance option with heavier procurement. |
| LSEG Tick History / PCAP | Institutional audit option, likely overbuilt for current S4-0. |
| Barchart Market Replay / historical futures data | Lower-friction historical/replay candidate. |

## 3. Current S4-0 Requirement

The current S4-0 gate requires:

- Local/free or synthetic replay CSV with `ts_event`, `symbol`, and `price`.
- Declared front and next symbols.
- Source manifest, file hashes, and known source limitations.
- Timestamp semantics for the supplied source.
- Owner approval and no-money attestation.
- Forecast, decision, simulated execution, replay, restore, incident, and
  stop/go evidence.

## 4. Explicit Non-Requirements

These are no longer blockers for S4-0:

- Databento account access.
- CME direct licence.
- Licensed CL front/next data.
- Real tick-level data.
- Real order-book data.
- External reviewer access to raw exchange data.

## 5. Non-Claims

Passing S4-0 on local/free or synthetic replay does not prove:

- Profitability or alpha.
- Live-market readiness.
- Licensed-feed compliance.
- Real exchange timestamp quality.
- Real order-book reconstruction.
- Live execution quality.
