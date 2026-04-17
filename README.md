# multi-desk-trading

A multi-desk, agent-led coordination architecture for systematic trading research.

**Status**: capability-build / research only. Architecture-first, P&L-diagnostic.

The deliverable is the orchestration machinery — contracts, message bus, attribution, research loop — not a P&L number. The architecture is successful if it redeploys to an unrelated asset class with zero changes to shared infrastructure.

## Design document

- [`docs/architecture_spec_v1.md`](docs/architecture_spec_v1.md) — frozen v1 specification. Any change to §4, §6, §7, §8, §9, §10, or §11 requires a v2 bump.

## Layout

```
.
├── contracts/          # Pydantic v2 schemas — v1 frozen boundary (§4)
├── persistence/        # DuckDB schema + insert/read helpers (§3.2)
├── bus/                # Synchronous in-memory dispatcher + validator (§3.1)
├── grading/            # Forecast → Print matching + Grade emission (§4.7)
├── scheduler/          # Release-calendar cron + synthetic clock (§3.3)
├── provenance/         # Input-snapshot hashing + dirty-tree policy (§4.3)
├── desks/              # Per-desk implementations (§5). Storage & Curve
│                       # deepened; 5 others stubbed.
├── controller/         # Regime-conditional linear sizing + cold-start (§8)
├── attribution/        # LODO (signal + grading) + Shapley exact (§9)
├── research_loop/      # Dispatcher + periodic/event-driven handlers +
│                       # Shapley-proportional weight promoter with
│                       # held-out margin validation (§6, §8.3)
├── eval/               # Three-hard-gate harness + synthetic data (§7.1)
├── tests/              # 106 tests; ruff + mypy strict across major pkgs
└── docs/               # Architecture spec + review responses
```

## Domain instance

Phase 1 instantiates the architecture on crude oil (WTI/Brent). The portability test is an equity-VRP redeployment (Phase 2). See spec §1, §12.2, §14.2.

## Data and compute

Synthetic / research-only. Free public data sources only (EIA, OPEC MOMR text, JODI, CFTC COT, Caldara-Iacoviello GPR, scraped news). No Bloomberg, Argus, Platts, Kpler, Vortexa. No live capital. Inference local on 8GB unified memory; fine-tuning on borrowed compute if the per-desk escalation ladder (spec §7.3) demands it.

## Status

**Architecture complete end-to-end** (capability claim **asserted**, not verified;
§12.2 Phase 1 non-requirement). Every §-section of the spec has a working
implementation with tests. Verified capability requires the Phase 2 equity-VRP
redeployment.

- [x] v1.0 architecture spec frozen (2026-04-17)
- [x] v1.1–v1.3 review responses shipped (see `docs/reviews/`)
- [x] Week 0 scaffold — `contracts/v1.py`, DuckDB schema (11 tables), bus with
      registry + dirty-tree validation, grading harness, scheduler, provenance.
      Tag `scaffold-v1.0`. Load-bearing `test_boundary_purity.py` +
      `test_replay_determinism.py` green.
- [x] Weeks 1–2 — stubs for all six desks. Tag `stubs-v1.0`.
- [x] Desk 1 (Storage & Curve) classical-specialist deepen. Ridge over price
      features; Gate 1 +8.99% RMSE vs random walk, Gate 2 ρ_dev=+0.70,
      ρ_test=+0.64, Gate 3 hot-swap pass on AR(1) synthetic. Tag
      `storage-curve-classical-v0.1`.
- [x] Three-hard-gate evaluation harness — skill, sign-preservation
      (Kronos-RCA), hot-swap. Tag `gates-v1.0`.
- [x] Controller — regime-conditional linear sizing + cold-start
      (§14.8 uniform weights, microsecond-precision boot_ts, lex tie-break).
      Tag `controller-v1.0`.
- [x] Attribution — LODO signal-space + grading-space + exact Shapley for
      n ≤ 6. Tags `lodo-v0.1`, `shapley-v0.1`, `lodo-grading-v0.2`.
- [x] Replay determinism — Forecast/Print/Grade + Controller/LODO/Shapley
      payload-identical across runs. Tag `replay-determinism-v0.2`.
- [x] Phase 1 smoke test — full pipeline through every subsystem in one pass.
      Tag `phase1-smoke-v0.1`.
- [x] Research loop dispatcher — priority-ordered event processor + periodic
      and event-driven handlers. Tags `research-loop-v0.1`,
      `event-handlers-v0.1`.
- [x] Weight promotion (§8.3) — Shapley-proportional proposer + held-out
      margin validation. Tags `promotion-v0.2`, `promotion-v0.3`.
- [x] Synthetic market simulator + 5 desk classical specialists +
      staged observability. 5-factor latent state (Schwartz-Smith + OU
      + Hawkes), 4 regimes with sticky transitions, per-desk AR(1)
      return drivers. 3 observation modes (clean / controlled leakage
      / realistic contamination) each with its own integration test.
      `sim/` package + `desks/{supply,demand,geopolitics,macro}/`
      classical specialists + ground-truth regime classifier. Tags
      `phase-a-v0.1`, `phase-b-v0.1`, `phase-c-v0.1`, `phases-abc-v0.1`.
- [x] Spec v1.4 revision — §12.2 Logic-gate / Reliability-gate split
      + §14.9 operator-side Reliability-gate commitment.
- [ ] Real HDP-HMM regime classifier (v0.2; debit logged in Phase A
      classifier docstring).
- [ ] Real data ingest pipelines (EIA WPSR / CFTC COT / JODI / FRED /
      news scraping for geopolitics LLM extraction).
- [ ] LLM two-tier routing postcondition gate (§6.4).
- [ ] Reliability gate: 28-day wall-clock soak test (§14.9 — operator
      commitment required).
- [ ] Phase 2: equity-VRP portability test (3 months after Phase 1 exit).

## License

MIT. See [`LICENSE`](LICENSE).
