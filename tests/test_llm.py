from __future__ import annotations

import json

import httpx

from pr.llm import GatewayLLM

BASE_URL = "http://gateway.test/v1"


def _reply(payload: dict):
    """A mock gateway that echoes `payload` as the assistant message content (JSON string)."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads(request.content)
        # Structured output must be requested as a json_schema response_format.
        assert body["response_format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(payload)}}]},
        )

    return httpx.Client(transport=httpx.MockTransport(handler), base_url=BASE_URL)


def test_summarize_parses_title_and_statement():
    llm = GatewayLLM(client=_reply({"title": "T", "statement": "S"}))
    out = llm.summarize("people re-key invoices by hand")
    assert out == {"title": "T", "statement": "S"}


def test_merge_returns_bool():
    assert GatewayLLM(client=_reply({"same_problem": True})).merge("a", "b") is True
    assert GatewayLLM(client=_reply({"same_problem": False})).merge("a", "b") is False


def test_categorise_passes_enums_and_parses():
    payload = {
        "industry_primary": "real-estate",
        "industry_secondary": [],
        "function_primary": "document-generation",
        "function_secondary": ["data-entry-extraction"],
    }

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["schema"] = body["response_format"]["json_schema"]["schema"]
        content = json.dumps(payload)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=BASE_URL)
    out = GatewayLLM(client=client).categorise("x", ["real-estate"], ["document-generation"])
    assert out["industry_primary"] == "real-estate"
    # The taxonomy is enforced as an enum in the request schema, not just prompted.
    assert captured["schema"]["properties"]["industry_primary"]["enum"] == ["real-estate"]


def test_score_runs_on_gateway():
    from pr.llm import DIMENSIONS

    payload = {d: {"score": 3, "reason": "r", "evidence_quote": "q"} for d in DIMENSIONS}
    out = GatewayLLM(client=_reply(payload)).score("some problem text")
    assert set(out) == set(DIMENSIONS)
    assert out["frequency"]["score"] == 3
