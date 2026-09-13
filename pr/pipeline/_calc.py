"""Pure numeric helpers for clustering and scoring. No DB, no network — unit-tested directly."""

from __future__ import annotations

import math
from collections.abc import Sequence


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity in [-1, 1]. Returns 0.0 if either vector is all-zero."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def mean_vectors(vectors: Sequence[Sequence[float]]) -> list[float]:
    """Element-wise mean of equal-length vectors (a problem centroid)."""
    if not vectors:
        raise ValueError("cannot average zero vectors")
    n = len(vectors)
    dim = len(vectors[0])
    out = [0.0] * dim
    for vec in vectors:
        if len(vec) != dim:
            raise ValueError("vectors must be equal length")
        for i, x in enumerate(vec):
            out[i] += x
    return [x / n for x in out]


def distinct_author_count(authors: Sequence[str | None]) -> int:
    """Count distinct non-empty authors. 'eight unrelated people' is the signal, not raw posts."""
    return len({a for a in authors if a})


def compute_composite(
    scores: dict[str, int],
    weights: dict[str, float],
    primary_industry: str | None,
    penalty_amount: float,
    penalty_domains: set[str],
) -> float:
    """Weighted composite on a 0–5 scale, with the regulated-domain penalty (spec §6).

    The penalty is applied to `buildability` before weighting when the primary industry is
    regulated, then clamped to [0, 5]. `weights` are expected to sum to 1.0.
    """
    adjusted = dict(scores)
    if primary_industry is not None and primary_industry in penalty_domains:
        adjusted["buildability"] = max(
            0.0, min(5.0, adjusted["buildability"] + penalty_amount)
        )
    total = sum(weights[dim] * adjusted[dim] for dim in weights)
    return round(total, 4)
