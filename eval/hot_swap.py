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
