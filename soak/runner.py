"""Soak runner — orchestrates the Reliability-gate loop (plan fix 1-5).

Composition:
  - ResourceMonitor          → telemetry
  - IncidentDetector         → numeric thresholds + exception classification
  - CheckpointStore          → resume-safe state
  - Caller-supplied tick_fn  → what actually happens each sim-day

Separating tick_fn from the runner keeps the orchestration trivial to
unit-test (pass a lambda that increments a counter) and lets the
CLI wire up real desks/controller/bus at the edges.

Flow:
  1. Load checkpoint if `--resume` else start fresh with init state.
  2. Initial resource sample → set incident baseline.
  3. Loop until duration elapsed OR incident detected OR signal:
     a. tick_fn(state) advances one sim-day.
     b. Every sample_interval s: take sample + check incidents.
     c. Every checkpoint_interval s: save state.
     d. Sleep to achieve the configured wall-clock cadence.
  4. Final checkpoint + return SoakResult.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from contracts.v1 import SoakIncident

from .checkpoint import CheckpointStore, SoakState
from .incident import IncidentDetector
from .monitor import ResourceMonitor

TickFn = Callable[[SoakState], None]


@dataclass
class SoakResult:
    """Outcome of a completed soak run."""

    completed: bool  # True ⇒ reached target duration without incident
    final_state: SoakState
    incident: SoakIncident | None = None
    wall_clock_elapsed_s: float = 0.0
    n_samples: int = 0


@dataclass
class SoakRunner:
    """Real-time wall-clock soak-test orchestrator."""

    conn: duckdb.DuckDBPyConnection
    db_path: Path
    checkpoint_path: Path
    tick_fn: TickFn
    duration_seconds: float  # e.g. 7 * 86400 for production
    cadence_seconds: float = 60.0  # 1 sim-day per wall-minute default
    sample_interval_seconds: float = 60.0
    checkpoint_interval_seconds: float = 600.0  # every 10 min default
    seed: int = 0
    resume: bool = False
    status_callback: Callable[[dict[str, float]], None] | None = None
    _monitor: ResourceMonitor | None = field(default=None, init=False)
    _detector: IncidentDetector | None = field(default=None, init=False)
    _store: CheckpointStore | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._store = CheckpointStore(self.checkpoint_path)

    def _init_state(self) -> SoakState:
        if self.resume:
            loaded = self._store.load() if self._store else None
            if loaded is not None:
                return loaded
        return SoakState(
            sim_day_index=0,
            n_decisions_emitted=0,
            start_ts_utc=datetime.now(tz=UTC),
            seed=self.seed,
        )

    def run(self) -> SoakResult:
        state = self._init_state()
        # A fresh start gets a fresh start_ts_utc; a resumed run keeps
        # the original start time so elapsed is cumulative.
        if state.start_ts_utc is None:
            state.start_ts_utc = datetime.now(tz=UTC)

        def _count() -> int:
            return state.n_decisions_emitted

        monitor = ResourceMonitor(
            conn=self.conn,
            db_path=self.db_path,
            decision_count_fn=_count,
            start_ts_utc=state.start_ts_utc,
        )
        detector = IncidentDetector(conn=self.conn)
        baseline = monitor.sample()
        detector.set_baseline(baseline)
        n_samples = 1
        self._monitor = monitor
        self._detector = detector

        store = self._store
        if store is None:  # pragma: no cover — post_init always sets it
            store = CheckpointStore(self.checkpoint_path)
            self._store = store

        wall_start = time.monotonic()
        last_sample = wall_start
        last_checkpoint = wall_start
        incident: SoakIncident | None = None

        try:
            while True:
                elapsed = time.monotonic() - wall_start
                if elapsed >= self.duration_seconds:
                    break

                self.tick_fn(state)

                now = time.monotonic()
                if now - last_sample >= self.sample_interval_seconds:
                    s = monitor.sample()
                    n_samples += 1
                    inc = detector.check(s)
                    if inc is not None:
                        incident = inc
                        break
                    last_sample = now
                    if self.status_callback is not None:
                        self.status_callback(
                            {
                                "elapsed_s": float(elapsed),
                                "target_s": float(self.duration_seconds),
                                "rss_mb": s.rss_bytes / (1024 * 1024),
                                "open_fds": float(s.open_fds),
                                "n_decisions": float(s.n_decisions),
                            }
                        )
                if now - last_checkpoint >= self.checkpoint_interval_seconds:
                    store.save(state)
                    last_checkpoint = now

                if self.cadence_seconds > 0:
                    time.sleep(self.cadence_seconds)

        except KeyboardInterrupt:
            # Clean shutdown: save progress then rethrow so the CLI
            # exits with non-zero status (operator sees an interrupt).
            store.save(state)
            raise
        except Exception as e:  # noqa: BLE001 — broad catch by design
            # Exception-classed incident. Record and re-raise — the
            # caller decides whether the run continues (for transient
            # errors that bubble up from user code) or aborts.
            detector.record_exception(
                "scheduler_crash",
                {"type": type(e).__name__, "message": str(e)},
            )
            store.save(state)
            raise

        store.save(state)
        return SoakResult(
            completed=(incident is None),
            final_state=state,
            incident=incident,
            wall_clock_elapsed_s=time.monotonic() - wall_start,
            n_samples=n_samples,
        )
