"""Test helpers.

No network: sources are driven against recorded fixtures via httpx MockTransport.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def mock_client(payload: dict, base_url: str = "https://example.test") -> httpx.Client:
    """An httpx.Client that returns `payload` as JSON for every request."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler), base_url=base_url)


@pytest.fixture
def single_query(monkeypatch):
    """Constrain queries.yaml to one phrase / one subreddit so fetch counts are deterministic."""
    from pr import config

    cfg = {
        "phrases": ["is there a tool"],
        "hn": {"tags": ["story", "comment"], "max_pages": 1, "phrases": []},
        "reddit": {"subreddits": ["Landlord"], "limit": 50, "phrases": []},
    }
    monkeypatch.setattr(config, "load_queries", lambda: cfg)
    # sources import load_queries into their own namespace
    import pr.sources.hn as hn
    import pr.sources.reddit as reddit

    monkeypatch.setattr(hn, "load_queries", lambda: cfg)
    monkeypatch.setattr(reddit, "load_queries", lambda: cfg)
    return cfg
