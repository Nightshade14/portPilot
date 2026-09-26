"""Unit test for the cosine -> vectorSearchScore threshold conversion (S1: for a
cosine index, `vectorSearchScore = (1 + cos) / 2`). No Atlas connection needed."""

from __future__ import annotations

from portpilot.knowledge.store import (
    DEDUPE_COSINE_THRESHOLD,
    DEDUPE_SCORE_THRESHOLD,
    _cosine_to_vector_search_score,
)


def test_cosine_1_maps_to_score_1():
    assert _cosine_to_vector_search_score(1.0) == 1.0


def test_cosine_minus_1_maps_to_score_0():
    assert _cosine_to_vector_search_score(-1.0) == 0.0


def test_cosine_0_maps_to_score_half():
    assert _cosine_to_vector_search_score(0.0) == 0.5


def test_dedupe_threshold_0_92_converts_correctly():
    # (1 + 0.92) / 2 = 0.96
    assert DEDUPE_SCORE_THRESHOLD == _cosine_to_vector_search_score(DEDUPE_COSINE_THRESHOLD)
    assert abs(DEDUPE_SCORE_THRESHOLD - 0.96) < 1e-9
