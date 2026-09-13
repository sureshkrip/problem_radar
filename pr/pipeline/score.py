"""LLM scoring against the six-dimension rubric (spec §6).

Never overwrites: each run inserts a new `score` row carrying its `model` and `prompt_version`,
so a ranking shift can always be traced to the world changing vs a prompt edit (spec §3).
The regulated-domain penalty is applied here in code, not by the model.
"""

from __future__ import annotations

from typing import Any

from psycopg.types.json import Json

from ..llm import DIMENSIONS, LLM
from ._calc import compute_composite, distinct_author_count


def _clamp05(value: Any) -> int:
    return max(0, min(5, int(value)))


def _primary_industry(conn: Any, problem_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT c.slug FROM problem_category pc
        JOIN category c ON c.id = pc.category_id
        WHERE pc.problem_id = %s AND c.axis = 'industry' AND pc.is_primary = TRUE
        LIMIT 1
        """,
        (problem_id,),
    ).fetchone()
    return row["slug"] if row else None


def _context(conn: Any, problem_id: int) -> str:
    prob = conn.execute(
        "SELECT title, statement FROM problem WHERE id = %s", (problem_id,)
    ).fetchone()
    ev = conn.execute(
        """
        SELECT r.author, r.body, r.metrics FROM evidence e
        JOIN raw_item r ON r.id = e.raw_item_id
        WHERE e.problem_id = %s ORDER BY r.posted_at DESC NULLS LAST LIMIT 12
        """,
        (problem_id,),
    ).fetchall()
    authors = distinct_author_count([r["author"] for r in ev])
    lines = [
        f"TITLE: {prob['title']}",
        f"STATEMENT: {prob['statement']}",
        f"DISTINCT_AUTHORS: {authors}",
        "EVIDENCE (author — quote — metrics):",
    ]
    for r in ev:
        lines.append(f"- {r['author'] or 'anon'} — {r['body'][:400]} — {r['metrics']}")
    return "\n".join(lines)


def score_problem(
    conn: Any,
    problem_id: int,
    llm: LLM,
    weights: dict[str, float],
    penalty: dict[str, Any],
    model: str,
    prompt_version: str,
) -> dict[str, Any]:
    """Score one problem and insert a new score row. Returns the row's key fields."""
    raw = llm.score(_context(conn, problem_id))
    scores = {dim: _clamp05(raw[dim]["score"]) for dim in DIMENSIONS}
    rationale = {
        dim: {
            "reason": raw[dim].get("reason", ""),
            "evidence_quote": raw[dim].get("evidence_quote", ""),
        }
        for dim in DIMENSIONS
    }

    primary_industry = _primary_industry(conn, problem_id)
    composite = compute_composite(
        scores,
        weights,
        primary_industry,
        float(penalty.get("amount", -1.5)),
        set(penalty.get("domains", [])),
    )

    conn.execute(
        """
        INSERT INTO score
            (problem_id, model, prompt_version, frequency, pain, willingness_to_pay,
             buildability, fit, defensibility, composite, rationale)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            problem_id,
            model,
            prompt_version,
            scores["frequency"],
            scores["pain"],
            scores["willingness_to_pay"],
            scores["buildability"],
            scores["fit"],
            scores["defensibility"],
            composite,
            Json(rationale),
        ),
    )
    conn.commit()
    return {"problem_id": problem_id, "composite": composite, "scores": scores}
