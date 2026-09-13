"""Embeddings via the local LiteLLM gateway (OpenAI-compatible) → Qwen3-Embedding-0.6B (1024-dim).

One embedding per surviving item (spec §5). The gateway speaks the OpenAI `/v1/embeddings`
shape, so this is a thin client over `{model, input}` → `data[].embedding`. It accepts an
injected httpx.Client so tests drive it against fixtures with no network — same pattern as the
source clients. Endpoint, key, model and dimension are all env-configurable (see config.py).
"""

from __future__ import annotations

from collections.abc import Iterable

import httpx

from ..config import EMBED_BATCH_SIZE, EMBED_DIM, EMBED_MODEL, get_settings


class Embedder:
    """Turns text into EMBED_DIM-dim vectors. `embed()` preserves input order."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client

    def _client_or_default(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        settings = get_settings()
        # A LiteLLM virtual key is expected in production; a local gateway may run keyless in dev.
        headers = {}
        if settings.embed_api_key:
            headers["Authorization"] = f"Bearer {settings.embed_api_key}"
        return httpx.Client(
            base_url=settings.embed_base_url,
            timeout=60.0,
            headers=headers,
        )

    def embed(self, texts: Iterable[str]) -> list[list[float]]:
        items = list(texts)
        if not items:
            return []
        client = self._client_or_default()
        owns_client = self._client is None
        vectors: list[list[float]] = []
        try:
            for start in range(0, len(items), EMBED_BATCH_SIZE):
                batch = items[start : start + EMBED_BATCH_SIZE]
                resp = client.post(
                    "/embeddings",
                    json={"model": EMBED_MODEL, "input": batch},
                )
                resp.raise_for_status()
                data = resp.json()["data"]
                # OpenAI returns results with an `index` field; sort to be safe.
                for row in sorted(data, key=lambda r: r["index"]):
                    vec = row["embedding"]
                    if len(vec) != EMBED_DIM:
                        raise ValueError(
                            f"expected {EMBED_DIM}-dim embedding, got {len(vec)}"
                        )
                    vectors.append(vec)
        finally:
            if owns_client:
                client.close()
        return vectors

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
