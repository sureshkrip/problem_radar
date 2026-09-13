"""Hacker News source via the Algolia search API.

Endpoint: https://hn.algolia.com/api/v1/search_by_date
No auth. Be polite (~1 req/sec). We search each configured phrase, filtered to items created
at/after `since`, walking up to `max_pages` result pages.

Note (spec §13): hn.algolia.com is unreachable from some sandboxes (403 at the egress proxy).
The client is written against recorded fixtures; verify live ingest on the deploy box.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from ..config import load_queries
from ..models import RawItemDraft
from .base import Source

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
HITS_PER_PAGE = 50
POLITE_DELAY_S = 1.0


class HackerNewsSource(Source):
    slug = "hn"

    def _client_or_default(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(
            timeout=30.0,
            headers={"User-Agent": "problem-radar/0.1"},
        )

    def fetch(self, since: datetime) -> Iterator[RawItemDraft]:
        cfg = load_queries()
        hn_cfg = cfg.get("hn") or {}
        phrases = hn_cfg.get("phrases") or cfg.get("phrases") or []
        tags = hn_cfg.get("tags") or ["story", "comment"]
        max_pages = int(hn_cfg.get("max_pages", 3))
        since_i = int(since.timestamp())
        tag_filter = ",".join(tags) if isinstance(tags, list) else str(tags)
        # Algolia OR-of-tags syntax: (story,comment)
        tag_param = f"({tag_filter})" if "," in tag_filter else tag_filter

        client = self._client_or_default()
        owns_client = self._client is None
        try:
            for phrase in phrases:
                yield from self._search_phrase(
                    client, phrase, tag_param, since_i, max_pages, polite=owns_client
                )
        finally:
            if owns_client:
                client.close()

    def _search_phrase(
        self,
        client: httpx.Client,
        phrase: str,
        tag_param: str,
        since_i: int,
        max_pages: int,
        polite: bool,
    ) -> Iterator[RawItemDraft]:
        for page in range(max_pages):
            params = {
                "query": phrase,
                "tags": tag_param,
                "numericFilters": f"created_at_i>{since_i}",
                "page": page,
                "hitsPerPage": HITS_PER_PAGE,
            }
            resp = client.get(SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            hits = data.get("hits", [])
            for hit in hits:
                draft = _hit_to_draft(hit)
                if draft is not None:
                    yield draft
            if page + 1 >= data.get("nbPages", 0) or not hits:
                break
            if polite:
                time.sleep(POLITE_DELAY_S)


def _hit_to_draft(hit: dict) -> RawItemDraft | None:
    object_id = hit.get("objectID")
    if not object_id:
        return None
    # Body: story text, comment text, or fall back to the title.
    body = hit.get("story_text") or hit.get("comment_text") or hit.get("title") or ""
    if not body.strip():
        return None
    posted_at = None
    if hit.get("created_at_i"):
        posted_at = datetime.fromtimestamp(hit["created_at_i"], tz=UTC)
    url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
    return RawItemDraft(
        external_id=str(object_id),
        body=body,
        title=hit.get("title"),
        url=url,
        author=hit.get("author"),
        posted_at=posted_at,
        metrics={
            "points": hit.get("points"),
            "num_comments": hit.get("num_comments"),
            "tags": hit.get("_tags"),
        },
    )
