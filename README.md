# multi-desk-trading

A multi-desk, agent-led coordination architecture for systematic trading research.

**Status**: capability-build / research only. Architecture-first, P&L-diagnostic.

The deliverable is the orchestration machinery — contracts, message bus, attribution, research loop — not a P&L number. The architecture is successful if it redeploys to an unrelated asset class with zero changes to shared infrastructure.

## Design document

- [`docs/architecture_spec_v1.md`](docs/architecture_spec_v1.md) — frozen v1 specification. Any change to §4, §6, §7, §8, §9, §10, or §11 requires a v2 bump.

## Layout

```
.
├── contracts/          # Pydantic v2 schemas (contracts/v1.py once built)
├── desks/              # Per-desk implementations (skeleton; see spec §5)
├── tests/              # Boundary-purity, replay-determinism, gate tests
├── scripts/            # Operational entry points (scheduler, grading harness)
└── docs/               # Architecture spec and derived documents
```

## Domain instance

Phase 1 instantiates the architecture on crude oil (WTI/Brent). The portability test is an equity-VRP redeployment (Phase 2). See spec §1, §12.2, §14.2.

## Data and compute

Synthetic / research-only. Free public data sources only (EIA, OPEC MOMR text, JODI, CFTC COT, Caldara-Iacoviello GPR, scraped news). No Bloomberg, Argus, Platts, Kpler, Vortexa. No live capital. Inference local on 8GB unified memory; fine-tuning on borrowed compute if the per-desk escalation ladder (spec §7.3) demands it.

## Status

- [x] v1.0 architecture spec frozen (2026-04-17)
- [ ] Week 0 scaffold: `contracts/v1.py`, bus, DuckDB schema, grading harness, `tests/test_boundary_purity.py`
- [ ] Stubs for all six desks
- [ ] Desk 1 (Storage & Curve) deepened
- [ ] Desks 2–5 deepened (Geopolitics → Supply/Demand parallel → Macro)
- [ ] Controller weight matrix fitted
- [ ] Phase 2: equity-VRP portability test

## License

MIT. See [`LICENSE`](LICENSE).
