"""Checkpoint store for the Reliability-gate runner (plan fix 2).

Persists the runner's mutable state to disk every N minutes so that
operator-level interrupts (OS reboot, `brew upgrade`, laptop sleep,
power loss) do NOT reset the 7-day wall-clock. On restart, the runner
loads the last checkpoint and resumes from the stored sim-time +
decision counter.

Design choices:
  - Pickle format: fastest round-trip for the Pydantic-free SoakState
    dataclass. Future versions may switch to JSON for cross-language
    readability; pickle is fine for a single-language research tool.
  - Atomic write: the save path writes to a temp file and renames,
    so a crash during `.save()` can't corrupt an existing checkpoint.
  - `load()` returns `None` if no checkpoint exists OR if the file
    is unreadable (corrupted pickles are treated as "no checkpoint"
    — the runner restarts fresh rather than crashing).
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SoakState:
    """Everything the runner needs to resume after a restart.

    sim_day_index: next sim-day index to feed (monotonic; resumes here).
    n_decisions_emitted: cumulative decision count.
    start_ts_utc: original runner start time — preserved across restarts
        so the 7-day wall-clock elapsed calculation stays correct.
    seed: base seed for the synthetic data feed.
    """

    sim_day_index: int = 0
    n_decisions_emitted: int = 0
    start_ts_utc: datetime | None = None
    seed: int = 0
    extra: dict[str, object] = field(default_factory=dict)


@dataclass
class CheckpointStore:
    """Atomic save / load of SoakState to a file on disk."""

    path: Path

    def save(self, state: SoakState) -> None:
        """Atomic write via temp file + rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("wb") as fh:
            pickle.dump(state, fh)
        tmp.replace(self.path)

    def load(self) -> SoakState | None:
        """Return the last saved state, or None if missing / corrupted."""
        if not self.path.exists():
            return None
        try:
            with self.path.open("rb") as fh:
                obj = pickle.load(fh)
            if isinstance(obj, SoakState):
                return obj
            return None
        except (pickle.UnpicklingError, EOFError, OSError):
            return None

    def clear(self) -> None:
        """Remove the checkpoint file. Safe if the file doesn't exist."""
        if self.path.exists():
            self.path.unlink()
