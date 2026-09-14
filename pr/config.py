"""Runtime settings (env) and static config-file loading.

Env comes from the process environment, with a local `.env` loaded for development. All the
secrets listed in spec §11.3 live here. Config files (queries.yaml, scoring.yaml) are loaded
from the `config/` directory at the repo root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()

# Repo root = two levels up from this file (pr/config.py -> pr -> repo root).
REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = REPO_ROOT / "config"
SQL_DIR = REPO_ROOT / "sql"


# All generative jobs — summaries, ambiguous-band merge, categorisation AND the 6-dimension
# scoring rubric — run on the box's local LiteLLM gateway (OpenAI-compatible) → llama-gen
# (Qwen3-4B-Instruct). Enum/shape are enforced with a JSON-schema response_format (grammar-
# constrained on llama.cpp). No external provider key. Point GEN_MODEL at any gateway alias.
GEN_MODEL = os.environ.get("GEN_MODEL", "local-gen")

# Embeddings: routed through the local LiteLLM gateway on the box (OpenAI-compatible), served
# by llama-embed → Qwen3-Embedding-0.6B (1024-dim). Every value is env-overridable so the same
# code runs against any OpenAI-compatible embeddings endpoint. EMBED_DIM must match the
# vector(N) columns in sql/001_schema.sql — change both together.
EMBED_MODEL = os.environ.get("EMBED_MODEL", "local-embed")
EMBED_DIM = int(os.environ.get("EMBED_DIM", "1024"))
# llama-embed is a small CPU server (4 parallel); keep request batches small so one HTTP call
# stays well under the timeout, and give it a generous read timeout (local models are slow).
EMBED_BATCH_SIZE = int(os.environ.get("EMBED_BATCH_SIZE", "8"))
EMBED_TIMEOUT = float(os.environ.get("EMBED_TIMEOUT", "300"))
# Generation (categorise/summaries/merge/score) on the local 4B model can be slow, especially the
# multi-field scoring rubric; a long read timeout avoids spurious ReadTimeouts.
GEN_TIMEOUT = float(os.environ.get("GEN_TIMEOUT", "300"))

# Prompt version stamped on every score row (spec §3 invariant). Bump on prompt edits.
PROMPT_VERSION = "v1"


@dataclass(frozen=True)
class Settings:
    database_url: str
    reddit_client_id: str | None
    reddit_client_secret: str | None
    reddit_user_agent: str
    freelancer_api_token: str | None
    embed_base_url: str
    embed_api_key: str | None
    gen_base_url: str
    gen_api_key: str | None
    basic_auth_user: str | None
    basic_auth_pass: str | None


@lru_cache
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/problem_radar",
        ),
        reddit_client_id=os.environ.get("REDDIT_CLIENT_ID"),
        reddit_client_secret=os.environ.get("REDDIT_CLIENT_SECRET"),
        reddit_user_agent=os.environ.get(
            "REDDIT_USER_AGENT", "problem-radar/0.1 (single-user tool)"
        ),
        freelancer_api_token=os.environ.get("FREELANCER_API_TOKEN"),
        # LiteLLM gateway on the box (OpenAI-compatible). Base URL includes the /v1 prefix;
        # the embeddings path is appended in embed.py.
        embed_base_url=os.environ.get("EMBED_BASE_URL", "http://127.0.0.1:4000/v1"),
        embed_api_key=os.environ.get("EMBED_API_KEY"),
        # llama-gen lives behind the same gateway; the virtual key is shared unless overridden.
        gen_base_url=os.environ.get("GEN_BASE_URL", "http://127.0.0.1:4000/v1"),
        gen_api_key=os.environ.get("GEN_API_KEY") or os.environ.get("EMBED_API_KEY"),
        basic_auth_user=os.environ.get("RADAR_BASIC_AUTH_USER"),
        basic_auth_pass=os.environ.get("RADAR_BASIC_AUTH_PASS"),
    )


@lru_cache
def load_queries() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "queries.yaml")


@lru_cache
def load_scoring() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "scoring.yaml")


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}
