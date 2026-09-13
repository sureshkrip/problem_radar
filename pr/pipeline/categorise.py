"""Two-axis categorisation (spec §4), constrained to the enums from the category table."""

from __future__ import annotations

from typing import Any

from ..llm import LLM, load_categories


def _context(conn: Any, problem_id: int) -> str:
    prob = conn.execute(
        "SELECT title, statement FROM problem WHERE id = %s", (problem_id,)
    ).fetchone()
    quotes = conn.execute(
        """
        SELECT r.body FROM evidence e JOIN raw_item r ON r.id = e.raw_item_id
        WHERE e.problem_id = %s ORDER BY r.posted_at DESC NULLS LAST LIMIT 5
        """,
        (problem_id,),
    ).fetchall()
    parts = [f"TITLE: {prob['title']}", f"STATEMENT: {prob['statement']}", "EVIDENCE:"]
    parts += [f"- {q['body'][:400]}" for q in quotes]
    return "\n".join(parts)


def categorise_problem(conn: Any, problem_id: int, llm: LLM) -> dict[str, Any]:
    """Assign one primary + optional secondaries on each axis. Replaces prior assignments."""
    industries, functions = load_categories(conn)
    result = llm.categorise(_context(conn, problem_id), industries, functions)

    cat_id = {
        (r["axis"], r["slug"]): r["id"]
        for r in conn.execute("SELECT id, axis, slug FROM category").fetchall()
    }

    # Rebuild this problem's category rows from scratch (idempotent re-categorisation).
    conn.execute("DELETE FROM problem_category WHERE problem_id = %s", (problem_id,))

    def add(axis: str, slug: str, is_primary: bool) -> None:
        key = (axis, slug)
        if key not in cat_id:  # enum is server-enforced, but never trust blindly
            raise ValueError(f"model returned unknown {axis} slug: {slug!r}")
        conn.execute(
            """
            INSERT INTO problem_category (problem_id, category_id, is_primary)
            VALUES (%s, %s, %s)
            ON CONFLICT (problem_id, category_id) DO UPDATE SET is_primary = EXCLUDED.is_primary
            """,
            (problem_id, cat_id[key], is_primary),
        )

    add("industry", result["industry_primary"], True)
    add("function", result["function_primary"], True)
    for slug in result.get("industry_secondary", []):
        if slug != result["industry_primary"]:
            add("industry", slug, False)
    for slug in result.get("function_secondary", []):
        if slug != result["function_primary"]:
            add("function", slug, False)

    conn.commit()
    return result
