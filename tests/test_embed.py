from __future__ import annotations

import httpx
import pytest

from pr.config import EMBED_DIM
from pr.pipeline.embed import Embedder

# The gateway is OpenAI-compatible; the Embedder posts to a relative "/embeddings" against the
# client's base_url, so the mock client sets one.
BASE_URL = "http://gateway.test/v1"


def _embed_response(request: httpx.Request) -> httpx.Response:
    # Echo one EMBED_DIM vector per input, tagged with its index (out of order, to test sorting).
    import json

    assert request.url.path.endswith("/embeddings")
    inputs = json.loads(request.content)["input"]
    data = [
        {"index": i, "embedding": [float(i)] * EMBED_DIM, "object": "embedding"}
        for i in range(len(inputs))
    ]
    return httpx.Response(200, json={"data": list(reversed(data)), "model": "x", "object": "list"})


def _mock() -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(_embed_response), base_url=BASE_URL)


def test_embed_returns_ordered_vectors():
    emb = Embedder(client=_mock())
    vectors = emb.embed(["first", "second", "third"])
    assert len(vectors) == 3
    assert all(len(v) == EMBED_DIM for v in vectors)
    # index 0 → all 0.0, index 1 → all 1.0, etc. (order preserved despite reversed response)
    assert vectors[0][0] == 0.0
    assert vectors[1][0] == 1.0
    assert vectors[2][0] == 2.0


def test_embed_one():
    assert len(Embedder(client=_mock()).embed_one("hello")) == EMBED_DIM


def test_embed_empty_is_noop():
    # No client needed — empty input returns immediately without a request.
    assert Embedder().embed([]) == []


def test_embed_rejects_wrong_dimension():
    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]})

    emb = Embedder(client=httpx.Client(transport=httpx.MockTransport(bad), base_url=BASE_URL))
    with pytest.raises(ValueError):
        emb.embed(["x"])
