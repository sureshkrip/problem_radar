"""`radar` command-line interface.

Phase 1 implements: init-db, ingest, list. cluster/score/show/serve are stubbed and land in
later phases (spec §10).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import typer

from . import db
from .config import MODEL_FAST, MODEL_STRONG, PROMPT_VERSION, load_scoring
from .llm import DIMENSIONS, ClaudeLLM, GatewayLLM
from .pipeline import categorise as categorise_mod
from .pipeline import cluster as cluster_mod
from .pipeline import filter as noise_filter
from .pipeline import score as score_mod
from .pipeline.embed import Embedder
from .sources import REGISTRY

app = typer.Typer(add_completion=False, help="Problem Radar — signal collection & triage.")

_SINCE_RE = re.compile(r"^\s*(\d+)\s*([dhmw])\s*$", re.IGNORECASE)
_SINCE_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}


def parse_since(value: str) -> datetime:
    """Parse a relative window like '7d', '12h', '30m', '2w' into an absolute UTC datetime."""
    match = _SINCE_RE.match(value)
    if not match:
        raise typer.BadParameter(f"invalid --since {value!r}; use forms like 7d, 12h, 30m, 2w")
    amount, unit = int(match.group(1)), match.group(2).lower()
    return datetime.now(UTC) - timedelta(**{_SINCE_UNITS[unit]: amount})


@app.command("init-db")
def init_db_cmd() -> None:
    """Apply the schema, seed sources and categories."""
    db.init_db()
    typer.echo("init-db: schema applied; sources and categories seeded.")


@app.command()
def ingest(
    source: str | None = typer.Option(
        None,
        "--source",
        help="Source slug (hn, reddit, freelancer, appstore). Omit to run all API sources.",
    ),
    since: str = typer.Option("7d", "--since", help="Relative window, e.g. 7d, 2d, 12h."),
) -> None:
    """Fetch from a source (or all), filter noise, and upsert into raw_item (idempotent)."""
    since_dt = parse_since(since)
    slugs = [source] if source else list(REGISTRY.keys())
    for slug in slugs:
        if slug not in REGISTRY:
            raise typer.BadParameter(f"unknown source {slug!r}; known: {', '.join(REGISTRY)}")
    grand_total = {"fetched": 0, "filtered": 0, "inserted": 0, "duplicate": 0}
    for slug in slugs:
        counts = _ingest_one(slug, since_dt)
        typer.echo(
            f"[{slug}] fetched={counts['fetched']} filtered_noise={counts['filtered']} "
            f"inserted={counts['inserted']} duplicate={counts['duplicate']}"
        )
        for key in grand_total:
            grand_total[key] += counts[key]
    if len(slugs) > 1:
        typer.echo(
            f"[all] fetched={grand_total['fetched']} filtered_noise={grand_total['filtered']} "
            f"inserted={grand_total['inserted']} duplicate={grand_total['duplicate']}"
        )


def _ingest_one(slug: str, since_dt: datetime) -> dict[str, int]:
    counts = {"fetched": 0, "filtered": 0, "inserted": 0, "duplicate": 0}
    src = REGISTRY[slug]()
    with db.connect() as conn:
        sid = db.source_id(conn, slug)
        for draft in src.fetch(since_dt):
            counts["fetched"] += 1
            if noise_filter.is_noise(draft):
                counts["filtered"] += 1
                continue
            if db.insert_raw_item(conn, sid, draft) is None:
                counts["duplicate"] += 1
            else:
                counts["inserted"] += 1
        conn.execute("UPDATE source SET last_run_at = now() WHERE id = %s", (sid,))
        conn.commit()
    return counts


_LIST_SQL = """
SELECT * FROM (
    SELECT
        p.id, p.title, p.status,
        (SELECT composite FROM score WHERE problem_id = p.id
         ORDER BY scored_at DESC LIMIT 1) AS composite,
        (SELECT c.slug FROM problem_category pc JOIN category c ON c.id = pc.category_id
         WHERE pc.problem_id = p.id AND c.axis = 'industry' AND pc.is_primary LIMIT 1) AS industry,
        (SELECT c.slug FROM problem_category pc JOIN category c ON c.id = pc.category_id
         WHERE pc.problem_id = p.id AND c.axis = 'function' AND pc.is_primary LIMIT 1) AS function,
        (SELECT count(DISTINCT r.author) FROM evidence e JOIN raw_item r ON r.id = e.raw_item_id
         WHERE e.problem_id = p.id) AS authors
    FROM problem p
) q
WHERE (%(status)s::text IS NULL OR q.status = %(status)s::text)
  AND (%(industry)s::text IS NULL OR q.industry = %(industry)s::text)
  AND (%(function)s::text IS NULL OR q.function = %(function)s::text)
  AND (%(min_score)s::real IS NULL OR q.composite >= %(min_score)s::real)
ORDER BY q.composite DESC NULLS LAST, q.id DESC
LIMIT %(limit)s
"""


@app.command("list")
def list_cmd(
    status: str | None = typer.Option(None, "--status", help="new|shortlist|building|parked|dead"),
    industry: str | None = typer.Option(None, "--industry", help="Primary industry slug."),
    function: str | None = typer.Option(None, "--function", help="Primary function slug."),
    min_score: float | None = typer.Option(None, "--min-score", help="Min composite score."),
    limit: int = typer.Option(20, "--limit", help="Max rows to show."),
) -> None:
    """List clustered problems, ranked by composite score."""
    params = {
        "status": status,
        "industry": industry,
        "function": function,
        "min_score": min_score,
        "limit": limit,
    }
    with db.connect() as conn:
        rows = conn.execute(_LIST_SQL, params).fetchall()
    if not rows:
        typer.echo("(no problems — run `radar cluster` first)")
        return
    for row in rows:
        comp = f"{row['composite']:.2f}" if row["composite"] is not None else "  -- "
        tags = f"{row['industry'] or '?'}/{row['function'] or '?'}"
        title = (row["title"] or "").strip()[:60]
        typer.echo(
            f"{row['id']:>6}  {comp:>5}  {row['status']:<9} {row['authors']:>2}a  "
            f"{tags:<40} {title}"
        )


@app.command()
def cluster(
    rebuild: bool = typer.Option(False, "--rebuild", help="Discard problems, keep raw_item."),
) -> None:
    """Embed raw items and cluster them into problems (spec §5)."""
    cfg = load_scoring().get("clustering", {})
    llm = GatewayLLM()  # summarise + ambiguous-band merge run on the local gateway
    with db.connect() as conn:
        counts = cluster_mod.cluster(conn, Embedder(), llm, cfg, rebuild=rebuild)
    typer.echo(
        f"cluster: embedded={counts['embedded']} attached={counts['attached']} "
        f"merged_llm={counts['merged_llm']} created={counts['created']}"
    )


@app.command()
def score(
    all_: bool = typer.Option(False, "--all", help="Re-score every problem (fast model)."),
    top: int | None = typer.Option(None, "--top", help="Re-score top N by composite (strong)."),
) -> None:
    """Categorise (if needed) and score problems against the rubric (spec §6)."""
    scoring = load_scoring()
    weights = scoring["weights"]
    penalty = scoring.get("regulated_penalty", {})
    strong = top is not None
    model = MODEL_STRONG if strong else MODEL_FAST
    llm = ClaudeLLM(model)  # scoring stays on Claude
    cat_llm = GatewayLLM()  # categorisation runs on the local gateway

    with db.connect() as conn:
        if strong:
            rows = conn.execute(
                """
                SELECT p.id FROM problem p
                JOIN LATERAL (SELECT composite FROM score WHERE problem_id = p.id
                              ORDER BY scored_at DESC LIMIT 1) s ON TRUE
                ORDER BY s.composite DESC NULLS LAST LIMIT %s
                """,
                (top,),
            ).fetchall()
        elif all_:
            rows = conn.execute("SELECT id FROM problem ORDER BY id").fetchall()
        else:
            rows = conn.execute(
                """
                SELECT p.id FROM problem p
                LEFT JOIN score s ON s.problem_id = p.id
                WHERE s.id IS NULL ORDER BY p.id
                """
            ).fetchall()

        scored = 0
        for row in rows:
            pid = row["id"]
            has_cat = conn.execute(
                "SELECT 1 FROM problem_category WHERE problem_id = %s LIMIT 1", (pid,)
            ).fetchone()
            if not has_cat:
                categorise_mod.categorise_problem(conn, pid, cat_llm)
            result = score_mod.score_problem(
                conn, pid, llm, weights, penalty, model, PROMPT_VERSION
            )
            scored += 1
            typer.echo(f"  scored problem {pid}: composite={result['composite']:.2f}")
    typer.echo(f"score: {scored} problem(s) scored with {model} (prompt {PROMPT_VERSION}).")


@app.command()
def show(problem_id: int) -> None:
    """Show a problem's statement, sub-scores, rationale, categories and evidence."""
    with db.connect() as conn:
        prob = conn.execute(
            "SELECT * FROM problem WHERE id = %s", (problem_id,)
        ).fetchone()
        if prob is None:
            typer.echo(f"no problem with id {problem_id}")
            raise typer.Exit(code=1)
        score_row = conn.execute(
            "SELECT * FROM score WHERE problem_id = %s ORDER BY scored_at DESC LIMIT 1",
            (problem_id,),
        ).fetchone()
        cats = conn.execute(
            """
            SELECT c.axis, c.slug, pc.is_primary FROM problem_category pc
            JOIN category c ON c.id = pc.category_id WHERE pc.problem_id = %s
            ORDER BY c.axis, pc.is_primary DESC
            """,
            (problem_id,),
        ).fetchall()
        evidence = conn.execute(
            """
            SELECT r.author, r.url, r.posted_at, s.slug AS source FROM evidence e
            JOIN raw_item r ON r.id = e.raw_item_id
            JOIN source s ON s.id = r.source_id
            WHERE e.problem_id = %s ORDER BY r.posted_at DESC NULLS LAST
            """,
            (problem_id,),
        ).fetchall()
        authors = len({e["author"] for e in evidence if e["author"]})

    typer.echo(f"# [{prob['id']}] {prob['title']}  ({prob['status']})")
    typer.echo(f"\n{prob['statement']}\n")
    cat_str = ", ".join(
        f"{c['axis']}:{c['slug']}{'*' if c['is_primary'] else ''}" for c in cats
    ) or "(uncategorised)"
    typer.echo(f"Categories: {cat_str}")
    if score_row:
        typer.echo(f"\nComposite: {score_row['composite']:.2f}  "
                   f"({score_row['model']}, prompt {score_row['prompt_version']})")
        for dim in DIMENSIONS:
            r = score_row["rationale"].get(dim, {})
            typer.echo(f"  {dim:<20} {score_row[dim]}  {r.get('reason', '')}")
    else:
        typer.echo("\n(not scored yet — run `radar score`)")
    typer.echo(f"\nEvidence ({len(evidence)} items, {authors} distinct authors):")
    for e in evidence:
        when = e["posted_at"].strftime("%Y-%m-%d") if e["posted_at"] else "----------"
        typer.echo(f"  {when}  {e['source']:<10} {e['author'] or 'anon':<16} {e['url'] or ''}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
) -> None:
    """Run the keyboard-driven triage UI (spec §8)."""
    import uvicorn

    uvicorn.run("pr.web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    app()
