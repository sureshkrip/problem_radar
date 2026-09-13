-- Problem Radar schema. Target: Postgres 17 with the pgvector extension
-- (Coolify image variant: pgvector/pgvector:pg17). Idempotent where practical.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS source (
  id           SERIAL PRIMARY KEY,
  slug         TEXT UNIQUE NOT NULL,        -- 'hn', 'reddit', 'freelancer', 'clip'
  kind         TEXT NOT NULL,               -- 'api' | 'manual'
  config       JSONB NOT NULL DEFAULT '{}',
  enabled      BOOLEAN NOT NULL DEFAULT TRUE,
  last_run_at  TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS raw_item (
  id           BIGSERIAL PRIMARY KEY,
  source_id    INT NOT NULL REFERENCES source(id),
  external_id  TEXT NOT NULL,
  url          TEXT,
  author       TEXT,
  posted_at    TIMESTAMPTZ,
  title        TEXT,
  body         TEXT NOT NULL,
  metrics      JSONB NOT NULL DEFAULT '{}', -- upvotes, comment count, budget_min/max, currency, star_rating
  fetched_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  embedding    vector(1024),                -- Qwen3-Embedding-0.6B via local LiteLLM gateway
  triaged      BOOLEAN NOT NULL DEFAULT FALSE,
  UNIQUE (source_id, external_id)
);

CREATE TABLE IF NOT EXISTS problem (
  id           BIGSERIAL PRIMARY KEY,
  title        TEXT NOT NULL,
  statement    TEXT NOT NULL,               -- one-paragraph neutral statement of the problem
  status       TEXT NOT NULL DEFAULT 'new', -- new | shortlist | building | parked | dead
  first_seen   TIMESTAMPTZ NOT NULL,
  last_seen    TIMESTAMPTZ NOT NULL,
  notes        TEXT,
  centroid     vector(1024),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS evidence (
  problem_id   BIGINT NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
  raw_item_id  BIGINT NOT NULL REFERENCES raw_item(id) ON DELETE CASCADE,
  relevance    REAL NOT NULL DEFAULT 1.0,
  PRIMARY KEY (problem_id, raw_item_id)
);

CREATE TABLE IF NOT EXISTS category (
  id           SERIAL PRIMARY KEY,
  axis         TEXT NOT NULL,               -- 'industry' | 'function'
  slug         TEXT NOT NULL,
  name         TEXT NOT NULL,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  UNIQUE (axis, slug)
);

CREATE TABLE IF NOT EXISTS problem_category (
  problem_id   BIGINT NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
  category_id  INT NOT NULL REFERENCES category(id),
  is_primary   BOOLEAN NOT NULL DEFAULT FALSE,
  confidence   REAL,
  PRIMARY KEY (problem_id, category_id)
);

CREATE TABLE IF NOT EXISTS score (
  id                 BIGSERIAL PRIMARY KEY,
  problem_id         BIGINT NOT NULL REFERENCES problem(id) ON DELETE CASCADE,
  model              TEXT NOT NULL,
  prompt_version     TEXT NOT NULL,
  scored_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  frequency          SMALLINT NOT NULL,
  pain               SMALLINT NOT NULL,
  willingness_to_pay SMALLINT NOT NULL,
  buildability       SMALLINT NOT NULL,
  fit                SMALLINT NOT NULL,
  defensibility      SMALLINT NOT NULL,
  composite          REAL NOT NULL,
  rationale          JSONB NOT NULL,        -- {dimension: {reason, evidence_quote}}
  is_human_override  BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS raw_item_source_posted_idx ON raw_item (source_id, posted_at DESC);
CREATE INDEX IF NOT EXISTS raw_item_untriaged_idx     ON raw_item (triaged) WHERE triaged = FALSE;
CREATE INDEX IF NOT EXISTS score_problem_scored_idx   ON score (problem_id, scored_at DESC);
