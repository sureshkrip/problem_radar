"""FastAPI triage UI (spec §8).

One problem at a time, keyboard-driven, no mouse. Server-rendered Jinja fragments swapped by a
small vanilla-JS controller (pr/web/static/app.js) — no SPA, no external JS dependency.

Access control (spec §11.6): HTTP basic auth when RADAR_BASIC_AUTH_USER/PASS are set; open in
local dev when they aren't. /healthz is always open for Coolify's healthcheck.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import db
from ..config import get_settings, load_scoring
from ..llm import DIMENSIONS
from ..pipeline._calc import compute_composite
from ..sources import clip as clip_src

WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="Problem Radar", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

_basic = HTTPBasic(auto_error=False)

STATUSES = {"shortlist", "parked", "dead", "building", "new"}


def require_auth(credentials: HTTPBasicCredentials | None = Depends(_basic)) -> None:
    """Enforce basic auth only when both env vars are set (spec §11.6)."""
    settings = get_settings()
    if not settings.basic_auth_user or not settings.basic_auth_pass:
        return  # dev mode: no credentials configured
    ok = credentials is not None and (
        secrets.compare_digest(credentials.username, settings.basic_auth_user)
        and secrets.compare_digest(credentials.password, settings.basic_auth_pass)
    )
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"


def _bookmarklet(clip_endpoint: str) -> str:
    """A one-line bookmarklet (spec §2): grab title/url/selection and POST to /clip in a new tab.

    A dynamically-built form POST is used (not fetch) so it works cross-origin from any page with
    no CORS setup; the confirmation page renders in the new tab.
    """
    body = (
        "(function(){"
        "var t=document.title,u=location.href,"
        "s=(window.getSelection?window.getSelection().toString():'');"
        "var f=document.createElement('form');"
        f"f.method='POST';f.action='{clip_endpoint}';f.target='_blank';"
        "function a(n,v){var i=document.createElement('input');"
        "i.type='hidden';i.name=n;i.value=v;f.appendChild(i);}"
        "a('source_label',location.hostname);a('url',u);a('title',t);a('text',s||t);"
        "document.body.appendChild(f);f.submit();f.remove();"
        "})();"
    )
    return "javascript:" + body


@app.get("/clip", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def clip_page(request: Request) -> HTMLResponse:
    """Manual-capture page: a paste form plus a draggable bookmarklet."""
    clip_endpoint = str(request.url_for("clip_submit"))
    return templates.TemplateResponse(
        request,
        "clip.html",
        {"bookmarklet": _bookmarklet(clip_endpoint)},
    )


@app.post("/clip", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def clip_submit(
    request: Request,
    text: str = Form(...),
    source_label: str = Form("clip"),
    url: str = Form(""),
    title: str = Form(""),
    notes: str = Form(""),
) -> HTMLResponse:
    """Write one manual capture into the `clip` source (spec §2).

    The item is stored immediately (target: under five seconds) and picked up by the next
    `radar cluster` / `radar score` run, flowing through the identical downstream pipeline as
    every other raw_item. No noise filter is applied — a manual clip is a deliberate signal.
    """
    if not text.strip():
        raise HTTPException(400, "empty clip")
    draft = clip_src.build_draft(
        source_label=source_label.strip() or "clip",
        url=url.strip() or None,
        text=text,
        notes=notes.strip() or None,
        title=title.strip() or None,
    )
    with db.connect() as conn:
        sid = db.source_id(conn, "clip")
        new_id = db.insert_raw_item(conn, sid, draft)
        conn.commit()
    return templates.TemplateResponse(
        request,
        "clip_done.html",
        {"duplicate": new_id is None, "raw_item_id": new_id, "title": draft.title},
    )


def _queue_ids(conn: Any, cap: int) -> list[int]:
    """Untriaged problems (status 'new'), best-scored first, capped so the queue can't rot."""
    rows = conn.execute(
        """
        SELECT p.id,
               (SELECT composite FROM score WHERE problem_id = p.id
                ORDER BY scored_at DESC LIMIT 1) AS composite
        FROM problem p
        WHERE p.status = 'new'
        ORDER BY composite DESC NULLS LAST, p.id DESC
        LIMIT %s
        """,
        (cap,),
    ).fetchall()
    return [r["id"] for r in rows]


def _card_context(conn: Any, problem_id: int) -> dict[str, Any] | None:
    prob = conn.execute("SELECT * FROM problem WHERE id = %s", (problem_id,)).fetchone()
    if prob is None:
        return None
    score = conn.execute(
        "SELECT * FROM score WHERE problem_id = %s ORDER BY scored_at DESC LIMIT 1",
        (problem_id,),
    ).fetchone()
    cats = conn.execute(
        """
        SELECT c.axis, c.slug, pc.is_primary FROM problem_category pc
        JOIN category c ON c.id = pc.category_id WHERE pc.problem_id = %s
        """,
        (problem_id,),
    ).fetchall()
    evidence = conn.execute(
        """
        SELECT r.author, r.url, r.posted_at, r.body, s.slug AS source FROM evidence e
        JOIN raw_item r ON r.id = e.raw_item_id
        JOIN source s ON s.id = r.source_id
        WHERE e.problem_id = %s ORDER BY r.posted_at DESC NULLS LAST
        """,
        (problem_id,),
    ).fetchall()
    all_cats = conn.execute(
        "SELECT axis, slug FROM category WHERE is_active = TRUE ORDER BY axis, slug"
    ).fetchall()

    dims = []
    if score:
        for d in DIMENSIONS:
            r = score["rationale"].get(d, {})
            dims.append({
                "key": d,
                "value": score[d],
                "reason": r.get("reason", ""),
                "quote": r.get("evidence_quote", ""),
            })
    primary = {c["axis"]: c["slug"] for c in cats if c["is_primary"]}
    return {
        "p": prob,
        "score": score,
        "dims": dims,
        "primary_industry": primary.get("industry"),
        "primary_function": primary.get("function"),
        "industries": [c["slug"] for c in all_cats if c["axis"] == "industry"],
        "functions": [c["slug"] for c in all_cats if c["axis"] == "function"],
        "evidence": evidence,
        "authors": len({e["author"] for e in evidence if e["author"]}),
        "dimensions": DIMENSIONS,
    }


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_auth)])
def index(request: Request) -> HTMLResponse:
    cap = int(load_scoring().get("triage", {}).get("daily_queue_cap", 20))
    with db.connect() as conn:
        ids = _queue_ids(conn, cap)
    return templates.TemplateResponse(
        request, "index.html", {"queue": ids, "cap": cap}
    )


@app.get("/problem/{problem_id}/card", response_class=HTMLResponse,
         dependencies=[Depends(require_auth)])
def card(request: Request, problem_id: int) -> HTMLResponse:
    with db.connect() as conn:
        ctx = _card_context(conn, problem_id)
    if ctx is None:
        return HTMLResponse("<p>gone</p>", status_code=404)
    return templates.TemplateResponse(request, "card.html", {**ctx, "request": request})


@app.post("/problem/{problem_id}/status", dependencies=[Depends(require_auth)])
def set_status(problem_id: int, status: str = Form(...)) -> Response:
    if status not in STATUSES:
        raise HTTPException(400, f"bad status {status!r}")
    with db.connect() as conn:
        conn.execute("UPDATE problem SET status = %s WHERE id = %s", (status, problem_id))
        conn.commit()
    return Response(status_code=204)


@app.post("/problem/{problem_id}/statement", response_class=HTMLResponse,
          dependencies=[Depends(require_auth)])
def edit_statement(request: Request, problem_id: int, statement: str = Form(...)) -> HTMLResponse:
    with db.connect() as conn:
        conn.execute(
            "UPDATE problem SET statement = %s WHERE id = %s", (statement, problem_id)
        )
        conn.commit()
        ctx = _card_context(conn, problem_id)
    return templates.TemplateResponse(request, "card.html", {**ctx, "request": request})


@app.post("/problem/{problem_id}/override", response_class=HTMLResponse,
          dependencies=[Depends(require_auth)])
def override_score(
    request: Request, problem_id: int, dimension: str = Form(...), value: int = Form(...)
) -> HTMLResponse:
    """Insert a human-override score row, keeping the model's original (spec §3)."""
    if dimension not in DIMENSIONS or not (0 <= value <= 5):
        raise HTTPException(400, "bad override")
    scoring = load_scoring()
    weights = scoring["weights"]
    penalty = scoring.get("regulated_penalty", {})
    with db.connect() as conn:
        latest = conn.execute(
            "SELECT * FROM score WHERE problem_id = %s ORDER BY scored_at DESC LIMIT 1",
            (problem_id,),
        ).fetchone()
        if latest is None:
            raise HTTPException(400, "score the problem before overriding")
        scores = {d: latest[d] for d in DIMENSIONS}
        scores[dimension] = value
        rationale = dict(latest["rationale"])
        rationale.setdefault(dimension, {})
        rationale[dimension] = {
            **rationale.get(dimension, {}),
            "reason": "human override",
        }
        prim = conn.execute(
            """
            SELECT c.slug FROM problem_category pc JOIN category c ON c.id = pc.category_id
            WHERE pc.problem_id = %s AND c.axis = 'industry' AND pc.is_primary LIMIT 1
            """,
            (problem_id,),
        ).fetchone()
        composite = compute_composite(
            scores, weights, prim["slug"] if prim else None,
            float(penalty.get("amount", -1.5)), set(penalty.get("domains", [])),
        )
        from psycopg.types.json import Json

        conn.execute(
            """
            INSERT INTO score
                (problem_id, model, prompt_version, frequency, pain, willingness_to_pay,
                 buildability, fit, defensibility, composite, rationale, is_human_override)
            VALUES (%s, 'human', %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE)
            """,
            (
                problem_id, latest["prompt_version"],
                scores["frequency"], scores["pain"], scores["willingness_to_pay"],
                scores["buildability"], scores["fit"], scores["defensibility"],
                composite, Json(rationale),
            ),
        )
        conn.commit()
        ctx = _card_context(conn, problem_id)
    return templates.TemplateResponse(request, "card.html", {**ctx, "request": request})


@app.post("/problem/{problem_id}/category", response_class=HTMLResponse,
          dependencies=[Depends(require_auth)])
def change_category(
    request: Request, problem_id: int, axis: str = Form(...), slug: str = Form(...)
) -> HTMLResponse:
    if axis not in ("industry", "function"):
        raise HTTPException(400, "bad axis")
    with db.connect() as conn:
        cat = conn.execute(
            "SELECT id FROM category WHERE axis = %s AND slug = %s", (axis, slug)
        ).fetchone()
        if cat is None:
            raise HTTPException(400, f"unknown {axis} slug {slug!r}")
        # Demote the current primary on this axis, then set the chosen one as primary.
        conn.execute(
            """
            UPDATE problem_category SET is_primary = FALSE
            WHERE problem_id = %s AND is_primary = TRUE
              AND category_id IN (SELECT id FROM category WHERE axis = %s)
            """,
            (problem_id, axis),
        )
        conn.execute(
            """
            INSERT INTO problem_category (problem_id, category_id, is_primary)
            VALUES (%s, %s, TRUE)
            ON CONFLICT (problem_id, category_id) DO UPDATE SET is_primary = TRUE
            """,
            (problem_id, cat["id"]),
        )
        conn.commit()
        ctx = _card_context(conn, problem_id)
    return templates.TemplateResponse(request, "card.html", {**ctx, "request": request})
