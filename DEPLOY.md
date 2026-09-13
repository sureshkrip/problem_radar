# Deploying Problem Radar to Coolify (spec §11)

Coolify (on the Hetzner box) handles the container build, TLS, secrets, cron and DB backups, so
the app ships as a Dockerfile and nothing else. This is the authoritative env reference — the old
`.env.example` predates the local-LLM switch and is not maintained.

## 1. Database — create it first

New Resource → Databases → PostgreSQL, and pick the **PGVector** image variant (`pgvector/pgvector:pg17`)
from the version selector, not plain Postgres. Do **not** enable "Make it publicly available".

Coolify generates an **Internal URL** like `postgres://<user>:<pass>@<container>:5432/<db>` — use that
(private Docker network). The `vector` extension ships in the image but is enabled per-database by
our migration, so no manual `CREATE EXTENSION` is needed — `radar init-db` runs it.

## 2. Application

New Resource → Application → from this Git repository
(`https://github.com/sureshkrip/problem_radar.git`, branch `main`), build pack **Dockerfile**.

- Port: **8080**. Attach a domain, leave Let's Encrypt on.
- Healthcheck: point it at **`GET /healthz`** (returns `ok`, no auth) — otherwise a failed deploy
  can look successful.

### First-run: initialise the schema

The app does not auto-migrate. After the first successful deploy, run once (Coolify → the app's
terminal, or a one-off command):

```
uv run radar init-db
```

This applies `sql/*.sql` (schema + `CREATE EXTENSION vector` + seeds sources and the two taxonomies).

## 3. Environment variables

All runtime-only (none needed at build time). Set in Coolify → Environment Variables.

| Var | Purpose |
|---|---|
| `DATABASE_URL` | the Postgres resource's **Internal URL** |
| `ANTHROPIC_API_KEY` | scoring (Claude Haiku → Opus) |
| `EMBED_BASE_URL` | LiteLLM gateway, e.g. `http://<gateway-host>:4000/v1` — see networking note |
| `EMBED_API_KEY` | LiteLLM **virtual key** (not the master key) |
| `EMBED_MODEL` | `local-embed` (gateway alias → Qwen3-Embedding-0.6B) |
| `GEN_BASE_URL` | same gateway `…/v1` (defaults to the embed gateway if unset) |
| `GEN_API_KEY` | LiteLLM virtual key (falls back to `EMBED_API_KEY`) |
| `GEN_MODEL` | `local-gen` (gateway alias → Qwen3-4B-Instruct) |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` / `REDDIT_USER_AGENT` | Reddit ingest |
| `FREELANCER_API_TOKEN` | Freelancer ingest |
| `RADAR_BASIC_AUTH_USER` / `RADAR_BASIC_AUTH_PASS` | HTTP basic auth (see §6) |

Notes:
- `EMBED_DIM` defaults to **1024** (matches the `vector(1024)` schema and `local-embed`). Only set
  it if you change the embed model — and change `sql/001_schema.sql` to match.
- The app-store source needs no key (Apple RSS is public; Google Play via `google-play-scraper`).

### Gateway networking (important)

The LiteLLM gateway binds `127.0.0.1:4000` on the **host**, which a Coolify app container cannot
reach as `127.0.0.1`. Do one of:
- attach this app to the gateway's Docker network (`llm-stack`) and use the gateway's
  container name as the host, or
- use the host's private-network address / Docker bridge gateway IP.

Mint a dedicated **virtual key** for this project in the LiteLLM UI (`/ui`) for `EMBED_API_KEY` /
`GEN_API_KEY` — do not deploy with the master key.

## 4. Ingest + scoring on a schedule

Coolify → the app → Scheduled Tasks. One task per source; write the bare command (Coolify runs it
in the app container via `sh`). Schedules use the **server's** timezone. Stagger ingest and scoring
so scoring never runs mid-ingest.

| Name | Command | Frequency |
|---|---|---|
| ingest-hn | `uv run radar ingest --source hn --since 2d` | `0 */6 * * *` |
| ingest-reddit | `uv run radar ingest --source reddit --since 2d` | `0 */6 * * *` |
| ingest-freelancer | `uv run radar ingest --source freelancer --since 2d` | `0 3 * * *` |
| ingest-appstore | `uv run radar ingest --source appstore --since 7d` | `0 4 * * 1` |
| cluster-and-score | `uv run radar cluster && uv run radar score --top 50` | `30 4 * * *` |

`cluster` embeds (via `local-embed`) + clusters + summarises/merges and categorises (via
`local-gen`); `score` runs the rubric on Claude. Raise the default 300s task timeout for the
cluster-and-score task. A zero exit code only means the command ran — after the first run, check
rows actually landed.

## 5. Backups

Enable a scheduled **daily** backup on the Postgres resource; set a retention count. If S3-compatible
storage is configured in Coolify, enable the upload too (a backup on the same box as the DB is not a
backup). Restore one into a throwaway DB once and confirm the app reads it.

## 6. Access control

Coolify puts no auth in front of the app. Set `RADAR_BASIC_AUTH_USER` / `RADAR_BASIC_AUTH_PASS` —
the app then enforces HTTP basic auth on every route except `/healthz`. Manual capture lives at
**`/clip`** (paste form + draggable bookmarklet).
