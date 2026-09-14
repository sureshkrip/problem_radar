"""LLM helpers (all jobs run on the box's local LiteLLM gateway — no external provider key).

Four jobs the pipeline delegates to a model:
- `summarize`   → a neutral title + one-paragraph statement when creating a new problem
- `merge`       → the ambiguous-band merge/split decision during clustering (spec §5)
- `categorise`  → the two-axis taxonomy, constrained to the enums (spec §4)
- `score`       → the six-dimension rubric as strict JSON (spec §6)

`LLM` is a Protocol so tests inject a fake with no network. `GatewayLLM` is the real
implementation: OpenAI-compatible chat completions against the gateway (→ Qwen3-4B `local-gen`)
with a JSON-schema `response_format` that enforces shape and the taxonomy enums (grammar-
constrained on llama.cpp). We still validate and retry once on malformed JSON, per spec §6.
To route any job to a different model (including a Claude-backed alias), point `GEN_MODEL` at it
in the gateway — the app needs no provider SDK or key of its own.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import GEN_MODEL, get_settings

# The six scoring dimensions, in rubric order (spec §6).
DIMENSIONS = ["frequency", "pain", "willingness_to_pay", "buildability", "fit", "defensibility"]

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class LLM(Protocol):
    def summarize(self, text: str) -> dict[str, str]: ...
    def merge(self, item_text: str, problem_statement: str) -> bool: ...
    def categorise(
        self, text: str, industries: list[str], functions: list[str]
    ) -> dict[str, Any]: ...
    def score(self, text: str) -> dict[str, dict[str, Any]]: ...


SUMMARIZE_SYSTEM = (
    "Write a neutral, one-line title and a one-paragraph statement of the underlying "
    "problem described below. State the problem, not any proposed solution. No marketing."
)
MERGE_SYSTEM = (
    "Decide whether the NEW item describes the same underlying problem as the EXISTING "
    "problem. Same problem means a builder would solve both with one product. Return JSON."
)


def _summarize_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"title": {"type": "string"}, "statement": {"type": "string"}},
        "required": ["title", "statement"],
        "additionalProperties": False,
    }


def _merge_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {"same_problem": {"type": "boolean"}},
        "required": ["same_problem"],
        "additionalProperties": False,
    }


def _categorise_schema(industries: list[str], functions: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "industry_primary": {"type": "string", "enum": industries},
            "industry_secondary": {
                "type": "array",
                "items": {"type": "string", "enum": industries},
            },
            "function_primary": {"type": "string", "enum": functions},
            "function_secondary": {
                "type": "array",
                "items": {"type": "string", "enum": functions},
            },
        },
        "required": [
            "industry_primary",
            "industry_secondary",
            "function_primary",
            "function_secondary",
        ],
        "additionalProperties": False,
    }


def _dim_schema() -> dict[str, Any]:
    dim = {
        "type": "object",
        "properties": {
            "score": {"type": "integer"},
            "reason": {"type": "string"},
            "evidence_quote": {"type": "string"},
        },
        "required": ["score", "reason", "evidence_quote"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {d: dim for d in DIMENSIONS},
        "required": list(DIMENSIONS),
        "additionalProperties": False,
    }


class GatewayLLM:
    """The single LLM implementation — all four jobs run on the local gateway (spec §4/§5/§6).

    Talks to the box's LiteLLM gateway (OpenAI-compatible chat completions) → llama-gen
    (Qwen3-4B-Instruct). Shape and the taxonomy enums are enforced with a `response_format`
    JSON schema, grammar-constrained on llama.cpp, so the model can't emit an off-taxonomy slug
    or a malformed rubric. One-retry-on-malformed-JSON contract.
    """

    def __init__(self, client: httpx.Client | None = None, max_tokens: int = 1024) -> None:
        self.max_tokens = max_tokens
        self._client = client

    def _client_or_default(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        settings = get_settings()
        headers = {}
        if settings.gen_api_key:
            headers["Authorization"] = f"Bearer {settings.gen_api_key}"
        return httpx.Client(base_url=settings.gen_base_url, timeout=120.0, headers=headers)

    def _json(
        self, system: str, user: str, schema: dict[str, Any], max_tokens: int | None = None
    ) -> dict[str, Any]:
        client = self._client_or_default()
        owns_client = self._client is None
        last_err: Exception | None = None
        try:
            for _ in range(2):
                resp = client.post(
                    "/chat/completions",
                    json={
                        "model": GEN_MODEL,
                        "max_tokens": max_tokens or self.max_tokens,
                        "temperature": 0,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {"name": "out", "schema": schema, "strict": True},
                        },
                    },
                )
                resp.raise_for_status()
                text = resp.json()["choices"][0]["message"]["content"] or ""
                try:
                    return json.loads(text)
                except json.JSONDecodeError as exc:  # pragma: no cover - retry path
                    last_err = exc
        finally:
            if owns_client:
                client.close()
        raise ValueError(f"gateway returned non-JSON output: {last_err}")

    def summarize(self, text: str) -> dict[str, str]:
        return self._json(SUMMARIZE_SYSTEM, text, _summarize_schema())

    def merge(self, item_text: str, problem_statement: str) -> bool:
        user = f"EXISTING PROBLEM:\n{problem_statement}\n\nNEW ITEM:\n{item_text}"
        return bool(self._json(MERGE_SYSTEM, user, _merge_schema()).get("same_problem", False))

    def categorise(
        self, text: str, industries: list[str], functions: list[str]
    ) -> dict[str, Any]:
        schema = _categorise_schema(industries, functions)
        return self._json(_read_prompt("categorise_v1.md"), text, schema)

    def score(self, text: str) -> dict[str, dict[str, Any]]:
        # Larger budget: the rubric returns 6 dimensions, each with a reason + evidence quote.
        return self._json(_read_prompt("score_v1.md"), text, _dim_schema(), max_tokens=2048)


def _read_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def load_categories(conn: Any) -> tuple[list[str], list[str]]:
    """Active industry and function slugs from the DB (source of truth for the enums)."""
    rows = conn.execute(
        "SELECT axis, slug FROM category WHERE is_active = TRUE ORDER BY id"
    ).fetchall()
    industries = [r["slug"] for r in rows if r["axis"] == "industry"]
    functions = [r["slug"] for r in rows if r["axis"] == "function"]
    return industries, functions
