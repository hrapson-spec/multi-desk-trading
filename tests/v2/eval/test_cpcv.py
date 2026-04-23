"""CPCV split generator tests."""

from __future__ import annotations

from math import comb

import pytest

from v2.eval import CPCVParams, assert_no_label_leakage, generate_cpcv_splits
from v2.eval.cpcv import chronological_block_bounds


def test_block_bounds_cover_full_range():
    bounds = chronological_block_bounds(100, 10)
    assert bounds[0][0] == 0
    assert bounds[-1][1] == 99
    # Contiguous: each block's end + 1 == next block's start
    for (_, end), (start, _) in zip(bounds, bounds[1:], strict=False):
        assert end + 1 == start


def test_block_bounds_rejects_bad_n_blocks():
    with pytest.raises(ValueError):
        chronological_block_bounds(100, 0)
    with pytest.raises(ValueError):
        chronological_block_bounds(100, 200)


def test_generate_cpcv_splits_count():
    params = CPCVParams(n_blocks=10, test_blocks=2, horizon_days=5, embargo_days=5)
    splits = generate_cpcv_splits(1000, params=params)
    assert len(splits) == comb(10, 2)


def test_train_and_test_are_disjoint_with_purge():
    params = CPCVParams(n_blocks=10, test_blocks=2, horizon_days=5, embargo_days=5)
    splits = generate_cpcv_splits(1000, params=params)
    for split in splits:
        train_set = set(split.train_indices.tolist())
        test_set = set(split.test_indices.tolist())
        assert not (train_set & test_set)
        # There should be at least one purged index (horizon + embargo > 0).
        purged = 1000 - len(train_set) - len(test_set)
        assert purged > 0


def test_test_blocks_must_be_less_than_n_blocks():
    with pytest.raises(ValueError):
        generate_cpcv_splits(100, params=CPCVParams(n_blocks=5, test_blocks=5))


def test_purge_and_embargo_nonnegative():
    with pytest.raises(ValueError):
        generate_cpcv_splits(100, params=CPCVParams(horizon_days=-1))


def test_no_label_leakage_holds_for_default_params():
    params = CPCVParams(n_blocks=10, test_blocks=2, horizon_days=5, embargo_days=5)
    splits = generate_cpcv_splits(1000, params=params)
    for split in splits:
        assert_no_label_leakage(split, horizon_days=params.horizon_days)


def test_weaker_purge_exposes_leakage():
    # With horizon=5 but purge_days=0 (via CPCVParams.horizon_days=0),
    # no label-overlap purge is applied — but assert_no_label_leakage
    # still checks for horizon=5 overlap and should raise for at least
    # one training index adjacent to a test block.
    params = CPCVParams(n_blocks=5, test_blocks=1, horizon_days=0, embargo_days=0)
    splits = generate_cpcv_splits(100, params=params)
    # Now assert with horizon=5 — this SHOULD find leakage.
    leakage_found = False
    for split in splits:
        try:
            assert_no_label_leakage(split, horizon_days=5)
        except ValueError:
            leakage_found = True
            break
    assert leakage_found


def test_splits_cover_all_blocks_as_test():
    params = CPCVParams(n_blocks=10, test_blocks=2)
    splits = generate_cpcv_splits(1000, params=params)
    test_block_coverage = set()
    for s in splits:
        test_block_coverage.update(s.test_block_indices)
    assert test_block_coverage == set(range(10))
