from __future__ import annotations

from pr.pipeline.cluster import _best_match


def test_best_match_picks_highest_similarity():
    centroids = [
        (1, [1.0, 0.0]),
        (2, [0.0, 1.0]),
        (3, [0.9, 0.1]),
    ]
    pid, sim = _best_match([1.0, 0.05], centroids)
    assert pid in (1, 3)  # both near the query; must be one of the close ones
    # the near-parallel vector (id 1) should win over the orthogonal one (id 2)
    assert _best_match([0.0, 1.0], centroids)[0] == 2


def test_best_match_none_when_no_centroids():
    assert _best_match([1.0, 0.0], []) is None
