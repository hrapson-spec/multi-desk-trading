"""Unit tests for soak.checkpoint.CheckpointStore."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from soak import CheckpointStore, SoakState


def test_save_load_round_trip(tmp_path: Path):
    store = CheckpointStore(tmp_path / "ckpt.pkl")
    state = SoakState(
        sim_day_index=123,
        n_decisions_emitted=456,
        start_ts_utc=datetime(2026, 4, 16, 10, 0, 0, tzinfo=UTC),
        seed=42,
    )
    store.save(state)
    loaded = store.load()
    assert loaded is not None
    assert loaded.sim_day_index == 123
    assert loaded.n_decisions_emitted == 456
    assert loaded.start_ts_utc == state.start_ts_utc
    assert loaded.seed == 42


def test_load_returns_none_when_missing(tmp_path: Path):
    store = CheckpointStore(tmp_path / "does-not-exist.pkl")
    assert store.load() is None


def test_save_is_atomic_no_temp_left_behind(tmp_path: Path):
    store = CheckpointStore(tmp_path / "ckpt.pkl")
    store.save(SoakState(sim_day_index=1))
    assert (tmp_path / "ckpt.pkl").exists()
    # tmp file should have been renamed, not left behind
    assert not (tmp_path / "ckpt.pkl.tmp").exists()


def test_save_overwrites_previous(tmp_path: Path):
    store = CheckpointStore(tmp_path / "ckpt.pkl")
    store.save(SoakState(sim_day_index=1))
    store.save(SoakState(sim_day_index=2))
    loaded = store.load()
    assert loaded is not None
    assert loaded.sim_day_index == 2


def test_load_returns_none_on_corrupted_pickle(tmp_path: Path):
    path = tmp_path / "ckpt.pkl"
    path.write_bytes(b"this is not a valid pickle")
    store = CheckpointStore(path)
    # Corrupted pickle treated as "no checkpoint" — runner starts fresh.
    assert store.load() is None


def test_clear_removes_file(tmp_path: Path):
    store = CheckpointStore(tmp_path / "ckpt.pkl")
    store.save(SoakState(sim_day_index=5))
    assert store.load() is not None
    store.clear()
    assert store.load() is None


def test_clear_on_missing_file_is_safe(tmp_path: Path):
    store = CheckpointStore(tmp_path / "never.pkl")
    store.clear()  # should not raise
