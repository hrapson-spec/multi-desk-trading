"""Combinatorial Purged Cross-Validation (Layer-3 challenger).

Partitions a chronologically-ordered index into N contiguous blocks.
For each choice of `test_blocks` blocks out of N, returns a split with
embargoed + purged training indices.

Purge rule: for a test block spanning indices [a, b], any training
index i with i + horizon_days >= a AND i <= b + embargo_days is
purged (its label window overlaps the test region or falls inside the
embargo).

The v2.0 defaults (N=10, k=2, purge=5d, embargo=5d) yield C(10, 2) = 45
distinct splits per run.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np


@dataclass(frozen=True)
class CPCVParams:
    n_blocks: int = 10
    test_blocks: int = 2
    horizon_days: int = 5
    embargo_days: int = 5


@dataclass(frozen=True)
class CPCVSplit:
    split_id: int
    test_block_indices: tuple[int, ...]
    train_indices: np.ndarray
    test_indices: np.ndarray


def chronological_block_bounds(n: int, n_blocks: int) -> list[tuple[int, int]]:
    """Partition [0, n) into `n_blocks` contiguous ranges as evenly as possible.

    Returns inclusive (start, end) pairs suitable for index slicing:
        block i covers [start_i, end_i].
    """
    if n_blocks <= 0 or n_blocks > n:
        raise ValueError(f"n_blocks must be in (0, {n}], got {n_blocks}")
    edges = np.linspace(0, n, n_blocks + 1, dtype=int)
    return [(int(edges[i]), int(edges[i + 1]) - 1) for i in range(n_blocks)]


def generate_cpcv_splits(n_observations: int, *, params: CPCVParams) -> list[CPCVSplit]:
    if params.test_blocks >= params.n_blocks:
        raise ValueError(
            f"test_blocks ({params.test_blocks}) must be < n_blocks ({params.n_blocks})"
        )
    if params.horizon_days < 0 or params.embargo_days < 0:
        raise ValueError("horizon_days and embargo_days must be non-negative")

    bounds = chronological_block_bounds(n_observations, params.n_blocks)
    all_indices = np.arange(n_observations)
    splits: list[CPCVSplit] = []

    for split_id, test_block_ids in enumerate(
        combinations(range(params.n_blocks), params.test_blocks)
    ):
        test_mask = np.zeros(n_observations, dtype=bool)
        purge_mask = np.zeros(n_observations, dtype=bool)

        for tid in test_block_ids:
            a, b = bounds[tid]
            test_mask[a : b + 1] = True
            # Purge: any training i with i + horizon >= a AND i <= b + embargo
            # (label of i overlaps test block, or i is inside embargo window).
            lo = max(0, a - params.horizon_days)
            hi = min(n_observations - 1, b + params.embargo_days)
            purge_mask[lo : hi + 1] = True

        train_mask = ~test_mask & ~purge_mask
        train_idx = all_indices[train_mask]
        test_idx = all_indices[test_mask]
        splits.append(
            CPCVSplit(
                split_id=split_id,
                test_block_indices=tuple(test_block_ids),
                train_indices=train_idx,
                test_indices=test_idx,
            )
        )
    return splits


def assert_no_label_leakage(split: CPCVSplit, *, horizon_days: int) -> None:
    """Check that no training index's label window overlaps any test index.

    Raises ValueError if the purge was insufficient.
    """
    if split.test_indices.size == 0 or split.train_indices.size == 0:
        return
    test_set = set(split.test_indices.tolist())
    for i in split.train_indices:
        label_window = range(i, i + horizon_days + 1)
        for idx in label_window:
            if idx in test_set:
                raise ValueError(
                    f"label-window leakage: train index {i} with "
                    f"horizon={horizon_days} overlaps test index {idx}"
                )
