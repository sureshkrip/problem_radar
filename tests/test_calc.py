from __future__ import annotations

import math

import pytest

from pr.pipeline._calc import (
    compute_composite,
    cosine,
    distinct_author_count,
    mean_vectors,
)


def test_cosine_identical_and_orthogonal():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([1.0, 1.0], [1.0, 1.0]) == pytest.approx(1.0)


def test_cosine_zero_vector_is_zero():
    assert cosine([0.0, 0.0], [1.0, 2.0]) == 0.0


def test_mean_vectors():
    assert mean_vectors([[0.0, 2.0], [2.0, 4.0]]) == [1.0, 3.0]
    with pytest.raises(ValueError):
        mean_vectors([])
    with pytest.raises(ValueError):
        mean_vectors([[1.0], [1.0, 2.0]])


def test_distinct_author_count_ignores_none_and_dupes():
    assert distinct_author_count(["a", "a", "b", None, ""]) == 2
    assert distinct_author_count([None, None]) == 0


WEIGHTS = {
    "willingness_to_pay": 0.25,
    "frequency": 0.20,
    "pain": 0.20,
    "buildability": 0.15,
    "fit": 0.15,
    "defensibility": 0.05,
}


def test_composite_weighted_average():
    scores = dict.fromkeys(WEIGHTS, 4)  # all 4s
    # weights sum to 1.0, so composite of all-4 is 4.0
    result = compute_composite(scores, WEIGHTS, "it-devops", -1.5, {"healthcare"})
    assert result == pytest.approx(4.0)


def test_regulated_penalty_lowers_buildability():
    scores = {
        "willingness_to_pay": 5,
        "frequency": 5,
        "pain": 5,
        "buildability": 4,
        "fit": 5,
        "defensibility": 5,
    }
    domains = {"healthcare", "legal", "finance-accounting", "insurance"}
    unpenalised = compute_composite(scores, WEIGHTS, "it-devops", -1.5, domains)
    penalised = compute_composite(scores, WEIGHTS, "healthcare", -1.5, domains)
    # buildability weight is 0.15; a -1.5 hit → composite drops by 0.15 * 1.5 = 0.225
    assert unpenalised - penalised == pytest.approx(0.225)


def test_regulated_penalty_clamps_at_zero():
    scores = dict.fromkeys(WEIGHTS, 0)
    # buildability 0 + (-1.5) clamps to 0, not negative
    assert compute_composite(scores, WEIGHTS, "legal", -1.5, {"legal"}) == pytest.approx(0.0)


def test_composite_is_bounded():
    scores = dict.fromkeys(WEIGHTS, 5)
    assert compute_composite(scores, WEIGHTS, None, -1.5, set()) == pytest.approx(5.0)
    assert not math.isnan(compute_composite(scores, WEIGHTS, None, -1.5, set()))
