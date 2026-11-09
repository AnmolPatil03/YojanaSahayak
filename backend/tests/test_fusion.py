from __future__ import annotations

import pytest

from yojana.retrieve.fusion import reciprocal_rank_fusion


def test_rrf_matches_formula() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "b", "c"], ["c", "a"]], k=60))
    assert fused["a"] == pytest.approx(1 / 61 + 1 / 62)
    assert fused["b"] == pytest.approx(1 / 62)
    assert fused["c"] == pytest.approx(1 / 63 + 1 / 61)


def test_rrf_orders_by_score_and_rewards_agreement() -> None:
    fused = reciprocal_rank_fusion([["x", "y", "z"], ["y", "z", "x"]], k=60)
    assert [doc for doc, _ in fused] == ["y", "x", "z"]


def test_rrf_small_k_amplifies_top_ranks() -> None:
    small = dict(reciprocal_rank_fusion([["a", "b"]], k=1))
    assert small["a"] / small["b"] == pytest.approx(1.5)


def test_rrf_ties_are_stable() -> None:
    fused = reciprocal_rank_fusion([["a", "b"], ["b", "a"]], k=60)
    assert [doc for doc, _ in fused] == ["a", "b"]


def test_rrf_ignores_duplicates_within_a_list() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "a", "b"]], k=60))
    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 63)


def test_rrf_weights() -> None:
    fused = dict(reciprocal_rank_fusion([["a"], ["b"]], k=60, weights=[2.0, 1.0]))
    assert fused["a"] == pytest.approx(2 / 61)
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], weights=[1.0, 2.0])
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)


def test_rrf_empty() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []
