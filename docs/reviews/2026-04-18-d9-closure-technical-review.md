# D9 closure — technical review packet (2026-04-18, spec v1.14)

**Purpose.** Single document capturing the code, methods, and results for the
Gate 3 runtime hot-swap harness fix (D9). Intended to be read top-to-bottom
without clicking into the repo.

**Tag.** `gate3-runtime-harness-v1.14`
**Author.** Henri Rapson (with Claude Opus 4.7 — pair coded, critic-first).
**Review disposition.** Pre-implementation design review was run on the plan
(5 blocking + 6 major findings); all addressed before Commit 1. See §3.

---

## 1. Summary

Prior to v1.14, every integration-level Gate 3 callsite passed
`run_controller_fn=lambda: True, run_controller_with_stub_fn=lambda: True` to
`eval.gates.gate_hot_swap`. The literal boolean bypasses the Controller
entirely, so `gate3_hot_swap.passed == True` was a tautology. The gate shell
at `eval/gates.py:204` was correct — the fault was at the call sites.

**What changed at v1.14.**

1. New factory `eval.hot_swap.build_hot_swap_callables` returns two closures
   that actually run `Controller.decide()` twice (real desk, then stub swap)
   and assert the expected `combined_signal` delta + honest
   `contributing_ids` membership.
2. `eval.gates.gate_hot_swap` metrics gain `failure_mode ∈
   {"passed", "controller_exception", "assertion_failure"}` so
   assertion-based closure failures are distinguishable from uncaught
   Controller exceptions.
3. A latent Controller bug (B-4) was surfaced by the closed-loop exercise
   and fixed: a retired desk (weight=0) with a non-stale forecast was
   appended to `Decision.input_forecast_ids`, leaking into audit trails.
4. 7 integration-level callsites migrated off `lambda: True`. The 4
   shell-unit tests in `tests/test_gates.py` keep their `lambda: True`
   literals (they legitimately test `gate_hot_swap`'s pass-through contract,
   not the integration path).
5. Manifest reconciliation: spec v1.14 + phase1/phase2_mvp completion
   annotations + capability_debits D9 closure + RAID log I-09 closure +
   new D-14 decision row.

**Delta.** 20 files, +1222 / −101 lines across the 5 D9 commits
(git range `bbd5a28..gate3-runtime-harness-v1.14`; `bbd5a28` is the
last non-D9 commit — the `sim_oil_v2` Phase 3 plan that shipped just
before D9 work began, excluded from the delta here):

```
236a926 docs(spec,pm): v1.14 D9 closure + manifest reconciliation    (C5/5)
62e041f test(eval): two-desk combined_signal case + teardown audit   (C4/5)
3e573e1 test(eval): migrate 7 integration callsites                  (C3/5)
6fc5f98 fix(controller): exclude retired desks from contributing_ids (C2/5)
0ec4835 feat(eval): hot_swap helper + failure_mode schema + M-1 test (C1/5)
```

**Test results.** 397 passed + 1 skipped (v1.13 baseline: 392 passed + 1
skipped; delta +5 tests). ruff check + ruff format --check clean. Runtime
25.8s locally.

---

## 2. Diagnosis — why D9 existed

### 2.1 The tautology

`eval.gates.gate_hot_swap` accepts two `Callable[[], bool]` closures. If both
return `True`, the gate passes. Every pre-v1.14 integration callsite wired
both to `lambda: True`:

```python
# Example from the pre-v1.14 test_hedging_demand_gates.py
report = runner.run(
    desk_forecasts=fcasts,
    prints=prints,
    baseline_fn=rw_baseline,
    directional_split=(...),
    expected_sign="positive",
    run_controller_fn=lambda: True,               # ← tautology
    run_controller_with_stub_fn=lambda: True,     # ← tautology
)
```

The closures never touch the Controller, the DB, the bus, or the desk under
test. `report.gate3_hot_swap.passed == True` was guaranteed by construction.

### 2.2 Scope — how many call sites

Pre-flight `rg 'run_controller_fn=lambda: True' tests/` returned 10 matches
in 8 files. Break-down:

| File | Callsites | Disposition |
|---|---|---|
| `tests/test_gates.py` | 4 | **Keep** (shell-unit tests — legitimate pass-through contract testing) |
| `tests/test_hedging_demand_gates.py` | 1 | Migrate |
| `tests/test_dealer_inventory_gates.py` | 1 | Migrate |
| `tests/test_storage_curve_gates.py` | 2 | Migrate (one helper covers both) |
| `tests/test_phase_a_clean_observations.py` | 1 | Migrate |
| `tests/test_phase_b_controlled_leakage.py` | 1 | Migrate |
| `tests/test_phase_c_realistic_contamination.py` | 1 | Migrate |
| `tests/test_logic_gate_multi_scenario.py` | 1 | Migrate (§12.2 item 2 load-bearing) |

**7 integration callsites migrated. 4 shell-unit callsites preserved.**

### 2.3 Latent Controller bug exposed by the fix (B-4)

Pre-v1.14 `controller/decision.py:96-104`:

```python
for row in weights:
    key = (row["desk_name"], row["target_variable"])
    f = recent_forecasts.get(key)
    if f is None:
        continue
    if f.staleness:
        continue
    w = float(row["weight"])
    combined_signal += w * float(f.point_estimate)
    contributing_ids.append(f.forecast_id)    # ← leaks retired desks
```

When `remediation.retire_desk_for_regime` writes a zero-weight SignalWeight
row, a retired desk's non-stale forecast contributes `0 * p = 0` to
`combined_signal` but its `forecast_id` still flows into
`Decision.input_forecast_ids`. This contaminates downstream Shapley
attribution (retired desks appear as contributing to decisions they didn't
actually influence) and audit trails.

The bug is invisible under `lambda: True` — the Gate 3 tautology meant no
test actually read `Decision.input_forecast_ids` under the retire code path.
The closed-loop exercise is what surfaced it.

---

## 3. Design review — the corrections that shaped the fix

Pre-implementation review flagged REQUEST_CHANGES with:

- **B-1 (blocking).** Original scope proposed migrating 2 equity-VRP
  callsites. Scope expansion: 7 integration callsites across Phase A/B/C +
  storage_curve + logic-gate-multi-scenario also need migration, or D9
  merely *moves*, it doesn't close.
- **B-2 (blocking).** Manifest reconciliation must land alongside code.
  Without spec §0 changelog + phase1/phase2_mvp annotations + debit closure,
  the audit trail claims v1.11/v1.12 passed Gate 3 at runtime, which is
  retroactively false.
- **B-3a (blocking).** Stub variant must not mutate caller's
  `recent_forecasts_other` dict. Two successive calls with the same shared
  dict would interfere if the helper mutated in place. Shallow-copy invariant.
- **B-3b (blocking).** `combined_signal` delta assertion must be guarded on
  real-forecast staleness. If the real forecast is stale, the real-run path
  skips it (`controller/decision.py:101-102`); the stub also skips; delta
  is zero by construction. The "real was non-stale" delta
  `-weight × point_estimate` applies only in that branch.
- **B-3c (blocking).** Factory must assert cold-start was seeded before
  returning closures — `controller_params` non-None,
  `signal_weights[desk]` non-zero. Otherwise Controller.decide raises or the
  delta is vacuously zero.
- **B-3d (blocking).** Stub emits `staleness=True` by construction
  (`StubDesk._build_stub_forecast`), so the stub path always takes the
  stale-skip branch. Document that in the helper.
- **B-4 (blocking).** Closed-loop exercise will likely surface the
  `contributing_ids` bug. Fix is on the critical path (part of D9 closure,
  not a separate ticket).
- **M-1 (major).** Add shell-unit test covering the AssertionError
  failure-mode branch (complementing the existing 3 shell tests which
  cover pass + generic-exception).
- **M-2 (major).** Extend metrics schema with `failure_mode` enum so
  reviewer can distinguish "Controller raised" from "assertion failed".
- **M-4 (major).** Two-desk same-target case must exist — the D8 production
  scenario (dealer_inventory ⊕ hedging_demand both → VIX_30D_FORWARD)
  is the one place the same-target invariant can be verified.
- **m-1 (minor).** Test-DB teardown audit — every migrated callsite must
  use pytest `tmp_path` or `:memory:`, documented in the closure evidence.
- **m-2 (minor).** Consider promoting shell signature
  `Callable[[], bool]` → `Callable[[], Decision]` (deferred; not in scope
  for v1.14 — would require spec bump).

All 5 blocking + 6 major findings incorporated into the revised plan **before
any code landed**. §4 explains how each claim is encoded in code.

---

## 4. Architecture of the fix

### 4.1 `eval/hot_swap.py` — the factory

**Full file** (/Users/henrirapson/projects/multi-desk-trading/eval/hot_swap.py,
265 lines):

```python
"""Gate 3 hot-swap runtime harness (spec v1.14).

Replaces `lambda: True` in integration gate-test wiring with closures that
actually exercise `Controller.decide()` against a seeded DuckDB state.
Each closure returns True iff the Controller produced a valid Decision
AND the post-exercise assertions (combined_signal delta, contributing_ids
membership) hold. An AssertionError propagates out so
`eval.gates.gate_hot_swap` can tag the `failure_mode` metric as
"assertion_failure" (distinguishing from "controller_exception").

Design: one factory, two closures, zero module-level state. Each call to
`build_hot_swap_callables` creates a fresh DB handle via the caller's
`conn` fixture (typically pytest `tmp_path` / per-test isolation per the
m-1 teardown audit). The factory performs pre-exercise sanity checks
(B-3c) before returning the closures — these are hard preconditions for
the gate to produce meaningful evidence; if they fail, the gate_hot_swap
call should not proceed.

B-3 corrections addressed:
  a. Stub closure operates on a **shallow copy** of `recent_forecasts_other`
     with the real desk's forecast replaced by a stub-generated null-signal
     forecast. Original dict is never mutated.
  b. The combined_signal delta assertion is **guarded on real-side
     staleness**: if the real forecast is stale, the delta is zero by
     construction and we assert combined_signal_real == combined_signal_stub.
     Otherwise we assert the standard delta.
  c. The factory **asserts before returning the closures** that the seeded
     DB has a non-None controller_params row and a non-zero signal_weights
     entry for the test desk. Without these, Controller.decide raises or
     the delta is vacuously zero.
  d. The stub emits `staleness=True` by construction
     (StubDesk._build_stub_forecast), so the stub-closure path always
     takes the "real=non-stale + stub=stale" branch when the real forecast
     is non-stale, and "real=stale + stub=stale" (trivial delta=0) when
     the real forecast is stale. The factory documents the resolved case
     in the closure's exercise log.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from contracts.v1 import (
    DirectionalClaim,
    EventHorizon,
    Forecast,
    Provenance,
    UncertaintyInterval,
)
from controller import Controller
from persistence import get_latest_controller_params, get_latest_signal_weights

if TYPE_CHECKING:
    import duckdb

    from contracts.v1 import RegimeLabel


@runtime_checkable
class _DeskLike(Protocol):
    """Structural interface the hot-swap helper needs from any desk.

    Keeps eval/ free of `desks.*` imports (§8.4 portability — shared
    infra must stay domain-neutral). Any desk class with matching
    attribute names satisfies this.
    """

    name: str
    target_variable: str
    event_id: str
    horizon_days: int


def _stub_forecast_for(
    *,
    name: str,
    target_variable: str,
    event_id: str,
    horizon_days: int,
    now_utc: datetime,
) -> Forecast:
    """Construct a StubDesk-style null-signal forecast for the hot-swap
    variant. Mirrors `StubDesk._build_stub_forecast` (desks/base.py:127)
    but parametrised by the real desk's attributes so the key
    (desk_name, target_variable) matches the weight row."""
    return Forecast(
        forecast_id=str(uuid.uuid4()),
        emission_ts_utc=now_utc,
        target_variable=target_variable,
        horizon=EventHorizon(
            event_id=event_id,
            expected_ts_utc=now_utc + timedelta(days=horizon_days),
        ),
        point_estimate=0.0,
        uncertainty=UncertaintyInterval(level=0.8, lower=-1e9, upper=1e9),
        directional_claim=DirectionalClaim(variable=target_variable, sign="none"),
        staleness=True,
        confidence=0.5,
        provenance=Provenance(
            desk_name=name,
            model_name="stub",
            model_version="0.0.0",
            input_snapshot_hash="0" * 64,
            spec_hash="0" * 64,
            code_commit="0" * 40,
        ),
    )


def build_hot_swap_callables(
    *,
    conn: duckdb.DuckDBPyConnection,
    real_desk: _DeskLike,
    real_forecast: Forecast,
    regime_label: RegimeLabel,
    recent_forecasts_other: dict[tuple[str, str], Forecast],
    now_utc: datetime,
) -> tuple[Callable[[], bool], Callable[[], bool]]:
    """Factory for Gate 3's (run_controller_fn, run_controller_with_stub_fn).

    Preconditions (B-3c): caller has already seeded the DB (typically via
    `controller.seed_cold_start`) such that:
      - `get_latest_controller_params(conn, regime_label.regime_id)` is non-None.
      - `get_latest_signal_weights(conn, regime_label.regime_id)` contains
        a row for `(real_desk.name, real_desk.target_variable)` with
        non-zero weight.

    Parameters:
      conn: DuckDB handle with cold-start seeded.
      real_desk: the desk under test. Used only for attribute wiring
        (name, target_variable, event_id, horizon_days).
      real_forecast: the desk's forecast to pass to Controller.decide.
        Staleness controls which delta-assertion branch runs.
      regime_label: passed to Controller.decide.
      recent_forecasts_other: other desks' forecasts to include; the real
        desk is added via `real_forecast`.
      now_utc: passed to Controller.decide + used to time-stamp the stub
        forecast (timezone-aware per spec §14.8).

    Returns (run_controller_fn, run_controller_with_stub_fn) — both
    Callable[[], bool], matching eval.gates.gate_hot_swap's signature.

    The closures raise AssertionError on post-exercise failures; the
    gate_hot_swap shell catches and tags failure_mode="assertion_failure".
    """
    # --- Pre-exercise sanity (B-3c) ------------------------------------
    params = get_latest_controller_params(conn, regime_label.regime_id)
    assert params is not None, (
        f"Controller params for regime {regime_label.regime_id!r} missing — "
        "seed cold-start before calling build_hot_swap_callables"
    )
    weights = get_latest_signal_weights(conn, regime_label.regime_id)
    weight_row = next(
        (
            w
            for w in weights
            if w["desk_name"] == real_desk.name
            and w["target_variable"] == real_desk.target_variable
        ),
        None,
    )
    assert weight_row is not None, (
        f"No SignalWeight row for ({real_desk.name!r}, "
        f"{real_desk.target_variable!r}) in regime {regime_label.regime_id!r}"
    )
    weight_for_desk = float(weight_row["weight"])
    assert weight_for_desk != 0.0, (
        f"SignalWeight for {real_desk.name!r} is zero; delta assertion "
        "would be vacuous. Seed a non-zero weight before the hot-swap test."
    )

    # Snapshot the real desk's forecast attributes for reuse in the stub.
    real_point_estimate = float(real_forecast.point_estimate)
    real_is_stale = bool(real_forecast.staleness)

    # Snapshot the shallow-copied forecast maps (B-3a).
    real_forecasts = dict(recent_forecasts_other)
    real_forecasts[(real_desk.name, real_desk.target_variable)] = real_forecast

    stub_forecast = _stub_forecast_for(
        name=real_desk.name,
        target_variable=real_desk.target_variable,
        event_id=real_desk.event_id,
        horizon_days=real_desk.horizon_days,
        now_utc=now_utc,
    )
    stub_forecasts = dict(recent_forecasts_other)
    stub_forecasts[(real_desk.name, real_desk.target_variable)] = stub_forecast

    controller = Controller(conn=conn)

    def _run_real() -> bool:
        decision = controller.decide(
            now_utc=now_utc,
            regime_label=regime_label,
            recent_forecasts=real_forecasts,
        )
        # Structural sanity.
        assert decision is not None, "Controller.decide returned None"
        assert decision.regime_id == regime_label.regime_id
        # Position clipping invariant.
        limit = float(params["pos_limit_regime"])
        assert -limit <= decision.position_size <= limit
        # contributing_ids membership (honest): the real desk's forecast_id
        # is present iff the forecast is non-stale AND weight is non-zero.
        if not real_is_stale:
            assert real_forecast.forecast_id in decision.input_forecast_ids, (
                f"Non-stale real forecast (weight={weight_for_desk}) absent from contributing_ids"
            )
        # Stash the real-run result on the closure so the stub closure
        # can compute the delta.
        _run_real.last_decision = decision  # type: ignore[attr-defined]
        return True

    def _run_stub() -> bool:
        # The real-run must have executed first; the stub delta depends
        # on combined_signal_real.
        real_decision = getattr(_run_real, "last_decision", None)
        assert real_decision is not None, (
            "Stub closure invoked before real closure — gate_hot_swap "
            "contract is (real first, stub second); check call order"
        )
        decision = controller.decide(
            now_utc=now_utc,
            regime_label=regime_label,
            recent_forecasts=stub_forecasts,
        )
        assert decision is not None
        limit = float(params["pos_limit_regime"])
        assert -limit <= decision.position_size <= limit
        # Stub forecasts emit staleness=True → they should NEVER appear in
        # contributing_ids regardless of real-forecast staleness.
        assert stub_forecast.forecast_id not in decision.input_forecast_ids, (
            "Stub (staleness=True) forecast_id leaked into contributing_ids — "
            "Controller's staleness skip at controller/decision.py:101-102 "
            "is broken"
        )
        # combined_signal delta (B-3b, B-3d).
        real_combined = float(real_decision.combined_signal)
        stub_combined = float(decision.combined_signal)
        if real_is_stale:
            # Real forecast was already skipped in the real run;
            # stub run also skips; delta is exactly zero.
            assert abs(stub_combined - real_combined) < 1e-9, (
                f"Stale-real + stale-stub expected zero delta; got "
                f"{stub_combined:.9f} vs {real_combined:.9f}"
            )
        else:
            # Real contributed weight*point; stub skipped. Delta is that amount.
            expected_delta = -weight_for_desk * real_point_estimate
            actual_delta = stub_combined - real_combined
            assert abs(actual_delta - expected_delta) < 1e-9, (
                f"combined_signal delta mismatch: expected "
                f"{expected_delta:.9f} (=-{weight_for_desk}*{real_point_estimate}), "
                f"got {actual_delta:.9f}"
            )
        return True

    return _run_real, _run_stub


__all__ = ["build_hot_swap_callables"]
```

**Claims this file encodes:**

| Claim | Line refs |
|---|---|
| §8.4 portability (no `desks.*` import from `eval/`) | `_DeskLike` at 62-74 (Protocol mirror of `StubDesk`) |
| B-3a (shallow-copy invariant) | 180-181, 190-191 (`dict(recent_forecasts_other)`) |
| B-3b (staleness-guarded delta) | 244-259 (`if real_is_stale` branch) |
| B-3c (pre-exercise DB assertions) | 150-173 |
| B-3d (stub always staleness=True) | 100, 236-240 (assertion that stub ID not in contributing_ids) |
| Position clipping invariant | 205-206, 232-233 |
| Honest `contributing_ids` for real side | 209-212 |

### 4.2 `eval/gates.py` — schema extension

Changes from v1.13 → v1.14:

**(a)** `GateResult.metrics` type widened `dict[str, float]` → `dict[str, float | str]`
(to hold the `failure_mode` string alongside numeric metrics):

```python
@dataclass
class GateResult:
    name: str
    passed: bool
    # metrics is heterogeneous: numeric keys like "desk_metric", "dev_rho",
    # plus string tags like "failure_mode" (spec v1.14 — see gate_hot_swap).
    # Consumers access specific known keys; treat as dict[str, object] at
    # read time and narrow per-key.
    metrics: dict[str, float | str] = field(default_factory=dict)
    reason: str = ""
```

**(b)** `gate_hot_swap` body (eval/gates.py:204-284):

```python
def gate_hot_swap(
    run_controller_fn: Callable[[], bool],
    run_controller_with_stub_fn: Callable[[], bool],
) -> GateResult:
    """The real desk and a stub version of it must both let the Controller
    run to completion. The caller wires this up; this function just records
    both outcomes and emits a structured result.

    run_controller_fn and run_controller_with_stub_fn each return True iff
    the Controller ran to completion under that configuration. At spec v1.14
    the callables may also raise AssertionError (from in-closure
    post-exercise assertions about Decision validity, combined_signal delta,
    or contributing_ids membership). AssertionError is distinguished from
    generic runtime exceptions via the `failure_mode` field in metrics.

    metrics schema:
      - real_ok: 0.0 | 1.0 — whether the real-desk closure returned True.
      - stub_ok: 0.0 | 1.0 — whether the stub-swap closure returned True.
      - failure_mode: "passed" | "controller_exception" | "assertion_failure"
        — distinguishes integration bugs (controller raised) from harness
        contract violations (closure asserted on Decision properties).
    """
    # Try real-desk closure. AssertionError caught first (narrower exception)
    # before the generic Exception branch.
    try:
        real_ok = bool(run_controller_fn())
    except AssertionError as e:
        return GateResult(
            name="hot_swap",
            passed=False,
            metrics={"real_ok": 0.0, "stub_ok": 0.0, "failure_mode": "assertion_failure"},
            reason=f"Real-desk closure assertion failed: {e!s}",
        )
    except Exception as e:
        return GateResult(
            name="hot_swap",
            passed=False,
            metrics={"real_ok": 0.0, "stub_ok": 0.0, "failure_mode": "controller_exception"},
            reason=f"Controller raised with real desk: {e!r}",
        )

    # Try stub-swap closure.
    try:
        stub_ok = bool(run_controller_with_stub_fn())
    except AssertionError as e:
        return GateResult(
            name="hot_swap",
            passed=False,
            metrics={
                "real_ok": 1.0 if real_ok else 0.0,
                "stub_ok": 0.0,
                "failure_mode": "assertion_failure",
            },
            reason=f"Stub-swap closure assertion failed: {e!s}",
        )
    except Exception as e:
        return GateResult(
            name="hot_swap",
            passed=False,
            metrics={
                "real_ok": 1.0 if real_ok else 0.0,
                "stub_ok": 0.0,
                "failure_mode": "controller_exception",
            },
            reason=f"Controller raised after hot-swap to stub: {e!r}",
        )

    passed = real_ok and stub_ok
    return GateResult(
        name="hot_swap",
        passed=passed,
        metrics={
            "real_ok": 1.0 if real_ok else 0.0,
            "stub_ok": 1.0 if stub_ok else 0.0,
            "failure_mode": "passed" if passed else "controller_exception",
        },
        reason=(
            f"Controller run real={real_ok} stub={stub_ok}; "
            f"{'passed' if passed else 'failed — boundary has drifted'}"
        ),
    )
```

Key design point: `except AssertionError` is listed **before**
`except Exception` on each try-block, so the harness-contract failure mode
is tagged correctly and not subsumed under the generic exception handler.

### 4.3 `controller/decision.py` — B-4 fix

Diff (the only functional change — 3 lines added):

```diff
     for row in weights:
         key = (row["desk_name"], row["target_variable"])
         f = recent_forecasts.get(key)
         if f is None:
             continue
         if f.staleness:
             continue
         w = float(row["weight"])
+        # v1.14: exclude retired desks (weight=0) from contributing_ids.
+        # A zero weight means the desk was retired via §7.2 auto-retire
+        # or v1.7 feed-reliability retirement; its forecast contributes
+        # 0 to combined_signal but must not leak into attribution /
+        # audit trails. Without this guard, Shapley on same-target
+        # desks would misattribute under the zero-weight case.
+        if w == 0.0:
+            continue
         combined_signal += w * float(f.point_estimate)
         contributing_ids.append(f.forecast_id)
```

**Semantic effect.** Before: retired desk with non-stale forecast → 0
contribution to `combined_signal`, `forecast_id` still in
`Decision.input_forecast_ids`. After: retired desk → 0 contribution,
forecast_id **also** excluded. This matches intent of
`research_loop.remediation.retire_desk_for_regime`, which writes weight=0
precisely to remove a desk from decisions.

---

## 5. Migration pattern (C3/5 — 7 callsites)

Every migrated callsite follows the same 5-step pattern:

```python
# 1. Connect to an isolated tmp_path DuckDB.
conn = connect(tmp_path / f"gate3_{name}.duckdb")
init_db(conn)

# 2. Seed cold-start (satisfies B-3c assertions).
seed_cold_start(
    conn,
    desks=[(name, target_variable)],       # or the full desk list for multi-desk
    regime_ids=["regime_boot"],             # Phase 1 tests; Phase A/B/C uses the 4-regime set
    boot_ts=NOW - timedelta(hours=1),
)

# 3. Pick a non-stale forecast (or fall back to index-0 if none available).
real_forecast = next(
    (f for f in drive["forecasts"] if not f.staleness),
    drive["forecasts"][0],
)

# 4. Construct a RegimeLabel matching the seeded regime_id.
regime_label = RegimeLabel(
    classification_ts_utc=NOW,
    regime_id="regime_boot",
    regime_probabilities={"regime_boot": 1.0},
    transition_probabilities={"regime_boot": 1.0},
    classifier_provenance=Provenance(
        desk_name="regime_classifier",
        model_name="stub", model_version="0.0.0",
        input_snapshot_hash="0" * 64,
        spec_hash="0" * 64,
        code_commit="0" * 40,
    ),
)

# 5. Build the callables and wire them into GateRunner.run.
real_fn, stub_fn = build_hot_swap_callables(
    conn=conn,
    real_desk=desk_instance,
    real_forecast=real_forecast,
    regime_label=regime_label,
    recent_forecasts_other={},              # or the multi-desk dict
    now_utc=NOW,
)
report = runner.run(
    ...,
    run_controller_fn=real_fn,
    run_controller_with_stub_fn=stub_fn,
)
assert report.gate3_hot_swap.passed
assert report.gate3_hot_swap.metrics["failure_mode"] == "passed"
assert report.gate3_hot_swap.metrics["real_ok"] == 1.0
assert report.gate3_hot_swap.metrics["stub_ok"] == 1.0
```

### 5.1 Migrated callsites (with notes)

| File | Callsite context | Notes |
|---|---|---|
| `tests/test_dealer_inventory_gates.py:213` | Equity-VRP MVP desk — Phase 2 Desk 1 | desk=`DealerInventoryDesk()`, target=`VIX_30D_FORWARD` |
| `tests/test_hedging_demand_gates.py:278` | Equity-VRP Desk 2 (hedging) — same target as dealer_inventory | desk=`HedgingDemandDesk()`, target=`VIX_30D_FORWARD`. G1/G2 pinned alongside (m-1). |
| `tests/test_storage_curve_gates.py:106, 250` | Oil load-bearing desk — 2 callsites, one helper | Extracted `_build_storage_curve_gate3_harness` helper. Stub-phase real_forecast is stale (triggers stale-real branch); classical-phase is non-stale (triggers delta branch). |
| `tests/test_phase_a_clean_observations.py:235` | 5-desk Phase A clean run | `_run_gates_for_desk` now takes `desk_instance` + `tmp_path` params |
| `tests/test_phase_b_controlled_leakage.py:205` | Phase B 10% leakage | DB name `gate3_phase_b_{name}.duckdb` keyed per desk |
| `tests/test_phase_c_realistic_contamination.py:233` | Phase C realistic mode | Per-desk DB within a single test via tmp_path subdir |
| `tests/test_logic_gate_multi_scenario.py:205` | §12.2 item 2 — 10 seeds × 5 desks | DB namespace `gate3_logic_{seed_tag}_{name}.duckdb` to avoid collision |

### 5.2 Shell-unit callsites preserved

4 callsites in `tests/test_gates.py` retain `lambda: True` / `lambda: raise`.
These are legitimate shell-contract tests — they verify the
`gate_hot_swap` function itself, not integration:

- `test_gate3_both_paths_pass` — both closures True → pass + failure_mode="passed"
- `test_gate3_real_desk_raises` — real raises → fail + failure_mode="controller_exception"
- `test_gate3_stub_swap_breaks` — stub raises → fail + failure_mode="controller_exception"
- `test_gate3_assertion_in_closure_fails` (new, M-1) — either side raises
  AssertionError → fail + failure_mode="assertion_failure"

---

## 6. New tests

### 6.1 `tests/test_gates.py::test_gate3_assertion_in_closure_fails` (M-1)

```python
def test_gate3_assertion_in_closure_fails():
    """Shell unit test (M-1): closure raises AssertionError (the path
    build_hot_swap_callables uses for post-exercise invariant violations)
    → failure_mode='assertion_failure'. Distinguishes harness-assertion
    failures from genuine Controller integration bugs."""

    def _assert_fail():
        raise AssertionError("combined_signal delta mismatch: got X expected Y")

    # Real side asserts.
    result = gate_hot_swap(
        run_controller_fn=_assert_fail,
        run_controller_with_stub_fn=lambda: True,
    )
    assert not result.passed
    assert result.metrics["failure_mode"] == "assertion_failure"
    assert "Real-desk closure assertion failed" in result.reason

    # Stub side asserts.
    result = gate_hot_swap(
        run_controller_fn=lambda: True,
        run_controller_with_stub_fn=_assert_fail,
    )
    assert not result.passed
    assert result.metrics["failure_mode"] == "assertion_failure"
    assert "Stub-swap closure assertion failed" in result.reason
```

### 6.2 `tests/test_controller_retire_exclusion.py` — B-4 regression

**Full file** (182 lines). Test 1 demonstrates the fix:

```python
def test_retired_desk_not_in_contributing_ids(conn):
    """Pre-retire: storage_curve + supply both contribute to the Decision.
    After retire_desk_for_regime writes a zero-weight SignalWeight row
    for supply, the next Controller.decide() call must NOT include
    supply's forecast_id in input_forecast_ids — even though the
    forecast itself is non-stale."""
    seed_cold_start(
        conn,
        desks=[
            ("storage_curve", WTI_FRONT_MONTH_CLOSE),
            ("supply", WTI_FRONT_MONTH_CLOSE),
        ],
        regime_ids=["regime_boot"],
        boot_ts=BOOT_TS,
    )

    ctrl = Controller(conn=conn)
    sc_forecast = _fcast("storage_curve", 82.0, NOW_TS)
    sup_forecast = _fcast("supply", 78.0, NOW_TS)
    recent = {
        ("storage_curve", WTI_FRONT_MONTH_CLOSE): sc_forecast,
        ("supply", WTI_FRONT_MONTH_CLOSE): sup_forecast,
    }

    # --- Pre-retire: both desks contribute ------------------------------
    d_pre = ctrl.decide(now_utc=NOW_TS, regime_label=_regime(NOW_TS), recent_forecasts=recent)
    assert sc_forecast.forecast_id in d_pre.input_forecast_ids
    assert sup_forecast.forecast_id in d_pre.input_forecast_ids
    # Uniform-weight: combined_signal = 0.5*82 + 0.5*78 = 80.
    assert d_pre.combined_signal == pytest.approx(80.0)

    # --- Retire supply --------------------------------------------------
    retire_desk_for_regime(
        conn,
        regime_id="regime_boot",
        desk_name="supply",
        target_variable=WTI_FRONT_MONTH_CLOSE,
        reason="test_retire_exclusion",
        now_utc=RETIRE_TS,
    )

    # --- Post-retire: supply MUST NOT appear in contributing_ids --------
    d_post = ctrl.decide(
        now_utc=RETIRE_TS, regime_label=_regime(RETIRE_TS), recent_forecasts=recent
    )
    assert sc_forecast.forecast_id in d_post.input_forecast_ids
    assert sup_forecast.forecast_id not in d_post.input_forecast_ids, (
        "Retired desk's forecast_id leaked into contributing_ids — "
        "controller/decision.py missing weight=0 exclusion guard"
    )
    # combined_signal = 0.5 * 82 + 0.0 * 78 = 41.0 (supply weight=0).
    assert d_post.combined_signal == pytest.approx(41.0)
```

Test 2 (`test_retired_desk_stale_forecast_also_excluded`) is a defensive
companion: a retired desk + a stale forecast should also be excluded,
hitting the same exclusion via the staleness branch instead of the
weight branch.

**B-4 validation**. Before the Controller fix, Test 1 failed with
`AssertionError: assert 'a58b8550-...' not in ['12a4afd8-...', 'a58b8550-...']`.
After the fix, both tests pass.

### 6.3 `tests/test_hot_swap_two_desk.py` (M-4)

Two tests covering the D8 same-target production scenario:

**Test 1.** `test_two_desk_swap_preserves_other_desk_contribution` — seeds
both `dealer_inventory` and `hedging_demand` (both targeting
`VIX_30D_FORWARD`, uniform weights 0.5 each). Baseline Decision has
`combined_signal = 0.5 * 20 + 0.5 * 25 = 22.5`. Then swaps desk A via
`build_hot_swap_callables`; the helper's delta assertion verifies that
swapping A preserves B's contribution. Same check for swapping B.

**Test 2.** `test_two_desk_swap_detects_cross_contamination_bug` — B-3a
shallow-copy invariant. Constructs a shared `recent_forecasts_other`
dict, builds a factory, calls both closures, and asserts the shared dict
is unmodified after the stub variant ran. If the helper mutated the dict
in place, the assertion would fail.

See `tests/test_hot_swap_two_desk.py` for the full 196-line file.

---

## 7. Results

### 7.1 Test count

| Suite | Count |
|---|---|
| v1.13 baseline | 392 passed + 1 skipped |
| v1.14 (D9 closed) | **397 passed + 1 skipped** |
| Delta | **+5 tests** (1 M-1 shell, 2 retire regression, 2 two-desk) |
| Runtime (local, 8GB M-series Mac) | 25.8s |

### 7.2 D9-specific test output

`uv run pytest tests/test_dealer_inventory_gates.py
tests/test_hedging_demand_gates.py tests/test_hot_swap_two_desk.py
tests/test_controller_retire_exclusion.py tests/test_gates.py -v` — 26/26 pass:

```
tests/test_dealer_inventory_gates.py::test_dealer_inventory_passes_hot_swap PASSED
tests/test_dealer_inventory_gates.py::test_dealer_inventory_stub_fails_skill_passes_hot_swap PASSED
tests/test_dealer_inventory_gates.py::test_dealer_inventory_classical_fits_and_predicts PASSED
tests/test_dealer_inventory_gates.py::test_dealer_inventory_falls_back_to_stub_when_unfit PASSED
tests/test_dealer_inventory_gates.py::test_dealer_inventory_classical_passes_three_gates_on_mvp_market PASSED
tests/test_dealer_inventory_gates.py::test_dealer_inventory_gate3_always_passes_strict PASSED
tests/test_hedging_demand_gates.py::test_hedging_demand_matches_deskprotocol PASSED
tests/test_hedging_demand_gates.py::test_hedging_demand_stub_fails_skill_passes_conformance PASSED
tests/test_hedging_demand_gates.py::test_hedging_demand_falls_back_to_stub_when_unfit PASSED
tests/test_hedging_demand_gates.py::test_hedging_demand_classical_fits_and_predicts PASSED
tests/test_hedging_demand_gates.py::test_hedging_demand_sign_derives_from_score PASSED
tests/test_hedging_demand_gates.py::test_hedging_demand_classical_three_gates_on_mvp_market PASSED
tests/test_hot_swap_two_desk.py::test_two_desk_swap_preserves_other_desk_contribution PASSED
tests/test_hot_swap_two_desk.py::test_two_desk_swap_detects_cross_contamination_bug PASSED
tests/test_controller_retire_exclusion.py::test_retired_desk_not_in_contributing_ids PASSED
tests/test_controller_retire_exclusion.py::test_retired_desk_stale_forecast_also_excluded PASSED
tests/test_gates.py::test_gate1_oracle_beats_persistence PASSED
tests/test_gates.py::test_gate1_stub_zero_fails_persistence PASSED
tests/test_gates.py::test_gate2_aligned_dev_and_test_passes PASSED
tests/test_gates.py::test_gate2_sign_flip_dev_to_test_fails PASSED
tests/test_gates.py::test_gate2_rejects_expected_sign_mismatch_on_dev PASSED
tests/test_gates.py::test_gate3_both_paths_pass PASSED
tests/test_gates.py::test_gate3_real_desk_raises PASSED
tests/test_gates.py::test_gate3_stub_swap_breaks PASSED
tests/test_gates.py::test_gate3_assertion_in_closure_fails PASSED
tests/test_gates.py::test_gate_report_all_passed_aggregates PASSED
============================== 26 passed in 1.20s ==============================
```

### 7.3 Full suite static checks

```
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
125 files already formatted
```

### 7.4 Git diff stats — D9 scope (`bbd5a28..gate3-runtime-harness-v1.14`)

```
 controller/decision.py                        |  11 +-
 docs/architecture_spec_v1.md                  |   4 +-
 docs/capability_debits.md                     |  79 +++---
 docs/phase1_completion.md                     |  10 +
 docs/phase2_mvp_completion.md                 |   2 +-
 docs/pm/master_plan.md                        |   9 +-
 docs/pm/raid_log.md                           |   3 +-
 eval/__init__.py                              |   2 +
 eval/gates.py                                 |  53 +++-
 eval/hot_swap.py                              | 265 +++   (new)
 tests/test_controller_retire_exclusion.py     | 181 +++   (new)
 tests/test_dealer_inventory_gates.py          |  62 ++++-
 tests/test_gates.py                           |  43 ++++
 tests/test_hedging_demand_gates.py            |  67 ++++-
 tests/test_hot_swap_two_desk.py               | 195 +++   (new)
 tests/test_logic_gate_multi_scenario.py       |  89 ++++-
 tests/test_phase_a_clean_observations.py      |  67 ++++-
 tests/test_phase_b_controlled_leakage.py      |  54 +++-
 tests/test_phase_c_realistic_contamination.py |  49 +++-
 tests/test_storage_curve_gates.py             |  78 +++++-
 20 files changed, 1222 insertions(+), 101 deletions(-)
```

(Aggregate against the pre-D9 tag `phase2-desk2-hedging-demand-v1.13`
is 21 files / +1571 / −101 because it also includes the unrelated
`docs/plans/sim_oil_v2.md` shipped in commit `bbd5a28`; that commit
documents a Phase 3 simulator proposal and is not part of the D9 ship
surface.)

### 7.5 Portability contract still green

Zero lines changed across the shared-infra packages enforced by
`tests/test_phase2_portability_contract.py` + `tests/test_phase2_equity_vrp_portability.py`:
`bus/`, `persistence/`, `research_loop/`, `attribution/`, `grading/`,
`provenance/`, `scheduler/`, `soak/`, `contracts/` (except the
append-only D9-unrelated additions from v1.12/v1.13), `desks/base.py`,
`desks/common/`, `sim/`, `sim_equity_vrp/`.

`eval/hot_swap.py` is deliberately designed to avoid a `desks.*` import
via the local `_DeskLike` Protocol (same pattern as
`soak/data_feed.py::_RegimeClassifierProtocol`).

### 7.6 Teardown audit (m-1)

All 30+ DB connections across the migrated callsites use pytest
`tmp_path` or `:memory:`, guaranteeing per-test isolation. Confirmed by
grep for `connect(` in test files and inspection of each hit — no
persistent DB path, no cross-test sharing.

---

## 8. Manifest reconciliation (C5/5)

Retroactively brings the audit trail into coherence so pre-v1.14
documents don't claim runtime hot-swap evidence that didn't exist.

| File | Change |
|---|---|
| `docs/architecture_spec_v1.md` | §0 changelog entry (v1.14). §15 derivation trace row tagged `gate3-runtime-harness-v1.14`. §16 sign-off v1.13 → v1.14. |
| `docs/phase1_completion.md` | §12.2 item 2 annotation: the 10/10 seed Gate 3 pass rate at v1.11 reflected attribute-conformance; v1.14 strengthens it to runtime hot-swap. |
| `docs/phase2_mvp_completion.md` | Gate 3 row annotation mirroring Phase 1. |
| `docs/capability_debits.md` | D9 Open → **Closed 2026-04-18 with scope caveat** (7 migrated callsites named). D7 wording updated. Closed-debits history extended. |
| `docs/pm/raid_log.md` | I-09 Open → Closed 2026-04-18. New D-14 decision row (fix-baseline-before-scale-out pattern). |
| `docs/pm/master_plan.md` | Spec v1.13 → v1.14. D9 milestone added to Completed. "before 2026-05-16" forward row struck through — Desk 3 no longer blocked. |

---

## 9. Reviewer checklist — what to verify

For a technical reviewer, the load-bearing checks are:

1. **Does `eval/hot_swap.py` actually exercise `Controller.decide()`?**
   Inspect `_run_real` (line 195) and `_run_stub` (line 218). Each calls
   `controller.decide(...)` with a concrete recent_forecasts dict.
   Previous `lambda: True` literally did nothing.

2. **Are the B-3 corrections encoded in the code, not just documented?**
   Every B-3 claim has a code anchor (table in §4.1). B-3c is the most
   rigorous — 4 assertion lines (150-173) that hard-fail before closure
   construction if cold-start wasn't seeded.

3. **Does the Controller fix actually change behaviour?**
   Run `tests/test_controller_retire_exclusion.py` against
   `git show 6fc5f98^:controller/decision.py` (pre-fix). Expected: test 1
   fails with a forecast_id leak. Against current code: both tests pass.

4. **Are the 7 migrated callsites truly exercising the Controller?**
   In each migrated file, verify the `run_controller_fn=real_fn` wiring.
   The `real_fn` name comes from `build_hot_swap_callables` — if it were
   still `lambda: True`, it would be inline.

5. **Is the portability contract preserved?**
   Run `uv run pytest tests/test_phase2_portability_contract.py
   tests/test_phase2_equity_vrp_portability.py`. Expected: both green.

6. **Is the shell unit test coverage complete?**
   `tests/test_gates.py` has 5 tests covering `gate_hot_swap` now:
   - pass / real-raises / stub-raises (3 existing, updated to include failure_mode)
   - assertion in closure (new, M-1)
   All 5 pass.

7. **Does the scope caveat on D9 closure honestly describe what was done?**
   `docs/capability_debits.md` D9 entry: "Closed 2026-04-18 with scope
   caveat — scope limited to the 7 migrated callsites identified in the
   D9 closure commit." — accurate. Any future integration Gate 3 test
   wiring `lambda: True` is expected to use `build_hot_swap_callables`
   instead (enforced by convention, not by grep — a future commit could
   add a `tests/test_no_lambda_true_in_integration.py` grep-contract if
   that's worth the noise-floor).

---

## 10. Known gaps / future work

- **m-2 (deferred, not in scope for v1.14).** Shell signature could be
  promoted from `Callable[[], bool]` to `Callable[[], Decision]`,
  letting `gate_hot_swap` inspect the Decision directly. Deferred to a
  future spec bump — would invalidate pinned metrics across the 7
  migrated tests.

- **No grep-contract preventing new `lambda: True` regressions.** If a
  future desk author wires `run_controller_fn=lambda: True` in a new
  integration test, code review is the only defence. Adding
  `tests/test_no_lambda_true_in_integration.py` that greps for the
  pattern and asserts zero matches outside `tests/test_gates.py` would
  close this — in scope for a future PR if noise becomes an issue.

- **D8 (same-target aggregation normalization) still open.** The M-4
  two-desk test pins that swapping preserves the other desk's
  contribution, but the Shapley-on-same-target problem it is scoped to
  (raw level-space aggregation) is unchanged. D9 closure does not close
  D8.

- **Multi-day leak detection.** Unrelated to D9, but the D9 work gave
  the Controller fix retroactive coverage. If a long-horizon property
  (e.g. attribution drift over 28 days) needs a runtime-hot-swap
  invariant, `build_hot_swap_callables` extends naturally.

---

**End of packet.** All code in this document lives under tag
`gate3-runtime-harness-v1.14` (commits `0ec4835`, `6fc5f98`, `3e573e1`,
`62e041f`, `236a926`). Full suite: 397 passed + 1 skipped.
