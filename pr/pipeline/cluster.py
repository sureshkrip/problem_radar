"""Clustering — the whole value of the tool (spec §5).

Collapse duplicate requests into one `problem` with an evidence trail:
- embed any raw_item that lacks an embedding,
- for each un-clustered item, cosine-match against existing problem centroids:
    ≥ attach_threshold        → attach evidence + recompute centroid,
    ambiguous band            → ask the LLM whether it's the same problem,
    below                     → create a new problem (LLM writes title + statement).

Matching runs in Python over the centroid set (small N), using the pure cosine helper — so
the logic is unit-testable without a live vector index.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pgvector.psycopg import register_vector

from ..llm import LLM
from ._calc import cosine, mean_vectors


def _as_list(vec: Any) -> list[float]:
    """pgvector may hand back a Vector object or a numpy array — normalise to a plain list."""
    if hasattr(vec, "to_list"):
        return vec.to_list()
    return list(vec)


def _best_match(
    vec: list[float], centroids: list[tuple[int, list[float]]]
) -> tuple[int, float] | None:
    """Return (problem_id, similarity) of the closest centroid, or None if there are none."""
    best: tuple[int, float] | None = None
    for pid, centroid in centroids:
        sim = cosine(vec, centroid)
        if best is None or sim > best[1]:
            best = (pid, sim)
    return best


def _item_text(row: dict[str, Any]) -> str:
    return f"{row.get('title') or ''}\n{row.get('body') or ''}".strip()


def cluster(
    conn: Any, embedder: Any, llm: LLM, cfg: dict[str, Any], rebuild: bool = False
) -> dict[str, int]:
    """Run the clustering pass. `cfg` is the `clustering` block of scoring.yaml."""
    register_vector(conn)
    attach = float(cfg.get("attach_threshold", 0.82))
    ambiguous_low = float(cfg.get("ambiguous_low", 0.72))
    counts = {"embedded": 0, "attached": 0, "merged_llm": 0, "created": 0}

    if rebuild:
        # Discard derived rows; raw_item (and its embeddings) is preserved. Spec §7 --rebuild.
        conn.execute("DELETE FROM problem")

    counts["embedded"] = _embed_missing(conn, embedder)

    items = conn.execute(
        """
        SELECT r.id, r.author, r.title, r.body, r.posted_at, r.embedding
        FROM raw_item r
        LEFT JOIN evidence e ON e.raw_item_id = r.id
        WHERE e.raw_item_id IS NULL AND r.embedding IS NOT NULL
        ORDER BY r.posted_at ASC NULLS LAST, r.id ASC
        """
    ).fetchall()

    for item in items:
        vec = _as_list(item["embedding"])
        centroids = _load_centroids(conn)
        match = _best_match(vec, centroids)
        posted = item["posted_at"] or datetime.now(UTC)

        if match and match[1] >= attach:
            _attach(conn, match[0], item["id"], posted)
            counts["attached"] += 1
        elif match and match[1] >= ambiguous_low and _ask_merge(conn, llm, match[0], item):
            _attach(conn, match[0], item["id"], posted)
            counts["merged_llm"] += 1
        else:
            _create_problem(conn, llm, item, vec, posted)
            counts["created"] += 1

    conn.commit()
    return counts


def _embed_missing(conn: Any, embedder: Any) -> int:
    rows = conn.execute(
        "SELECT id, title, body FROM raw_item WHERE embedding IS NULL ORDER BY id"
    ).fetchall()
    if not rows:
        return 0
    vectors = embedder.embed(_item_text(r) for r in rows)
    with conn.cursor() as cur:
        for row, vec in zip(rows, vectors, strict=True):
            cur.execute(
                "UPDATE raw_item SET embedding = %s WHERE id = %s", (vec, row["id"])
            )
    return len(rows)


def _load_centroids(conn: Any) -> list[tuple[int, list[float]]]:
    rows = conn.execute(
        "SELECT id, centroid FROM problem WHERE centroid IS NOT NULL"
    ).fetchall()
    return [(r["id"], _as_list(r["centroid"])) for r in rows]


def _ask_merge(conn: Any, llm: LLM, problem_id: int, item: dict[str, Any]) -> bool:
    row = conn.execute(
        "SELECT statement FROM problem WHERE id = %s", (problem_id,)
    ).fetchone()
    if row is None:
        return False
    return llm.merge(_item_text(item), row["statement"])


def _attach(conn: Any, problem_id: int, raw_item_id: int, posted: datetime) -> None:
    conn.execute(
        """
        INSERT INTO evidence (problem_id, raw_item_id) VALUES (%s, %s)
        ON CONFLICT (problem_id, raw_item_id) DO NOTHING
        """,
        (problem_id, raw_item_id),
    )
    conn.execute(
        """
        UPDATE problem
        SET first_seen = LEAST(first_seen, %s), last_seen = GREATEST(last_seen, %s)
        WHERE id = %s
        """,
        (posted, posted, problem_id),
    )
    _recompute_centroid(conn, problem_id)


def _recompute_centroid(conn: Any, problem_id: int) -> None:
    rows = conn.execute(
        """
        SELECT r.embedding FROM evidence e
        JOIN raw_item r ON r.id = e.raw_item_id
        WHERE e.problem_id = %s AND r.embedding IS NOT NULL
        """,
        (problem_id,),
    ).fetchall()
    vectors = [_as_list(r["embedding"]) for r in rows]
    if not vectors:
        return
    conn.execute(
        "UPDATE problem SET centroid = %s WHERE id = %s",
        (mean_vectors(vectors), problem_id),
    )


def _create_problem(
    conn: Any, llm: LLM, item: dict[str, Any], vec: list[float], posted: datetime
) -> None:
    summary = llm.summarize(_item_text(item))
    row = conn.execute(
        """
        INSERT INTO problem (title, statement, first_seen, last_seen, centroid)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (summary["title"], summary["statement"], posted, posted, vec),
    ).fetchone()
    conn.execute(
        "INSERT INTO evidence (problem_id, raw_item_id) VALUES (%s, %s)",
        (row["id"], item["id"]),
    )
