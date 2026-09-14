# Problem Radar

Private, single-user tool that collects "people have this problem" signals from the web,
clusters duplicates, categorises them, scores them with an LLM, and presents a triage queue.

See `problem-radar-spec.md` for the full build brief.

## Status

- **Phase 1 (ingest + store, HN + Reddit, no LLM)** — implemented.
- **Phase 2 (cluster + categorise + score, CLI)** — implemented.
- **Phase 3 (keyboard-driven triage UI, FastAPI)** — implemented.
- **Phase 4 (remaining sources: Freelancer, app-store reviews, `/clip` + bookmarklet)** — implemented.
- Phase 5 (deploy to Coolify) — pending.

### Sources (spec §2)

| Slug | Access | Signal |
|---|---|---|
| `hn` | Algolia search, no auth | unmet-need phrases |
| `reddit` | official API, OAuth2 client-credentials | unmet-need phrases in curated subs |
| `freelancer` | public REST API, `FREELANCER_API_TOKEN` | posted **budgets** = willingness-to-pay |
| `appstore` | Apple RSS review feed (+ `google-play-scraper` for Play) | 1–2 star reviews = "tool people hate" |
| `clip` | manual — `POST /clip` + bookmarklet | Upwork / G2 / Capterra (no scrapeable API) |

**Manual capture (`/clip`).** For sources that can't be scraped, visit `/clip` for a paste form and
a draggable bookmarklet (grabs title, URL and the selected text and posts them in one step). A clip
is written straight to `raw_item` under the `clip` source and joins a problem on the next
`radar cluster` run — the identical pipeline every other item flows through. No noise filter is
applied to a manual clip (it's a deliberate signal). App IDs / package names to watch for reviews
and the Freelancer query terms live in `config/queries.yaml`.

### Triage UI (`radar serve`, spec §8)

One problem at a time, keyboard-driven, no mouse. `j`/`k` next/prev · `s` shortlist · `p` park
· `x` dead · `e` edit statement · `1`–`6` then `0`–`5` override a sub-score · `c` change category.
The daily queue is capped (`scoring.yaml → triage.daily_queue_cap`, default 20) so it can't rot.
Basic auth turns on automatically when `RADAR_BASIC_AUTH_USER`/`PASS` are set (spec §11.6).

> **Note on the stack:** the spec names HTMX. This ships server-rendered Jinja fragments swapped
> by a small dependency-free vanilla-JS controller (`pr/web/static/app.js`) — same guarantees
> (server-rendered HTML, no SPA, keyboard-driven) with zero external JS to vendor or CDN-load.
> Actions are serialised (a busy lock + stale-response guard) so rapid key-mashing can't corrupt
> the queue.

## Stack

Python 3.11+, `httpx`, `psycopg[binary]` 3.x, FastAPI + Jinja2 + HTMX, `typer` CLI.
Postgres **17** with `pgvector` (Coolify image: `pgvector/pgvector:pg17`). Deps via `uv`.

**Embeddings:** the box's local **LiteLLM gateway** (OpenAI-compatible) → `llama-embed`
running **Qwen3-Embedding-0.6B** (1024-dim, matches the `vector(1024)` schema). No egress, no
per-call cost. Configure with `EMBED_BASE_URL` (default `http://127.0.0.1:4000/v1`),
`EMBED_API_KEY` (LiteLLM virtual key), `EMBED_MODEL` (the gateway's model alias) and `EMBED_DIM`
(default 1024 — must equal the `vector(N)` columns in `sql/001_schema.sql`).
**All generative jobs — categorise, summaries, merge, and the 6-dimension scoring rubric —**
run on the box's `llama-gen` → **Qwen3-4B-Instruct** via the same LiteLLM gateway, with a
JSON-schema `response_format` (grammar-constrained, so the taxonomy axes are enforced as enums and
the rubric can't come back malformed). Fully local: **no external provider key.** Configure with
`GEN_BASE_URL` (default = the gateway), `GEN_API_KEY` (defaults to `EMBED_API_KEY`), `GEN_MODEL`
(default `local-gen`). To route any job to a different model — including a Claude-backed alias —
point `GEN_MODEL` at it in the gateway; the app carries no provider SDK of its own. Full env
reference in [`DEPLOY.md`](DEPLOY.md).

## Local development

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
# 1. Start a local pgvector Postgres (matches production version)
docker run -d --name radar-pg \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=problem_radar \
  -p 5432:5432 pgvector/pgvector:pg17

# 2. Configure env
# create .env with the vars listed in DEPLOY.md (DATABASE_URL, EMBED_*/GEN_* gateway,
# REDDIT_*, FREELANCER_API_TOKEN, RADAR_BASIC_AUTH_*)

# 3. Install deps
uv sync

# 4. Apply schema + seed sources and categories
uv run radar init-db

# 5. Ingest and inspect
uv run radar ingest --source hn --since 2d
uv run radar ingest --source reddit --since 2d

# 6. Cluster into problems, then categorise + score (all via the local GEN_* gateway)
uv run radar cluster
uv run radar score --all          # score every problem
uv run radar score --top 20       # re-score just the top slice by composite
uv run radar list --min-score 3.5 --limit 20
uv run radar show <problem_id>
```

`radar ingest` is idempotent: running it twice adds zero duplicate rows
(`raw_item` has `UNIQUE (source_id, external_id)` and we upsert with `ON CONFLICT DO NOTHING`).

## Tests

No network — source clients are exercised against recorded fixtures in `tests/fixtures/`.

```bash
uv run pytest
uv run ruff check .
```

## CLI

```
radar init-db                          apply schema, seed sources and categories
radar ingest [--source hn] [--since 7d]
radar cluster [--rebuild]              embed + cluster raw items into problems
radar score [--all] [--top N]         categorise + score (fast pass / top-slice re-score)
radar list [--status] [--industry] [--function] [--min-score] [--limit]
radar show <problem_id>               statement, sub-scores, rationale, categories, evidence
radar serve                           triage UI on :8080 (Phase 3)
```

## Note on sandboxes

`hn.algolia.com` and the Reddit API are unreachable from some sandboxed environments
(HTTP 403 at the egress proxy). The clients are written against fixtures so the test suite
never touches the network; verify live ingest on the machine that will run it.
