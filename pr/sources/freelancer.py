"""Freelancer.com source via the public REST API.

Endpoint: GET https://www.freelancer.com/api/projects/0.1/projects/active
Auth: a `Freelancer-OAuth-V1: <token>` header (spec §2). The active-projects response carries
real budget figures — that stated budget is the willingness-to-pay signal (spec §2), so we
persist it into `metrics` (budget_min/max, currency, bid stats).

We search each configured query term, keep projects submitted at/after `since`, and map each to
a RawItemDraft. `full_description=true` asks the API for the full project text rather than a
truncated preview.

Note (spec §13): verify live ingest on the deploy box — the API needs a real token.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from ..config import get_settings, load_queries
from ..models import RawItemDraft
from .base import Source

SEARCH_URL = "https://www.freelancer.com/api/projects/0.1/projects/active"
POLITE_DELAY_S = 1.0


class FreelancerSource(Source):
    slug = "freelancer"

    def fetch(self, since: datetime) -> Iterator[RawItemDraft]:
        cfg = load_queries()
        f_cfg = cfg.get("freelancer") or {}
        queries = f_cfg.get("queries") or []
        limit = int(f_cfg.get("limit", 50))
        since_ts = since.timestamp()

        client = self._client
        owns_client = client is None
        if client is None:
            client = self._build_authed_client()
        try:
            for query in queries:
                yield from self._search(client, query, limit, since_ts)
                if owns_client:
                    time.sleep(POLITE_DELAY_S)
        finally:
            if owns_client:
                client.close()

    def _build_authed_client(self) -> httpx.Client:
        settings = get_settings()
        if not settings.freelancer_api_token:
            raise RuntimeError("FREELANCER_API_TOKEN is not set — cannot query the API.")
        return httpx.Client(
            timeout=30.0,
            headers={
                "Freelancer-OAuth-V1": settings.freelancer_api_token,
                "User-Agent": "problem-radar/0.1",
            },
        )

    def _search(
        self, client: httpx.Client, query: str, limit: int, since_ts: float
    ) -> Iterator[RawItemDraft]:
        resp = client.get(
            SEARCH_URL,
            params={
                "query": query,
                "limit": limit,
                "full_description": "true",
                "project_statuses[]": "active",
                "sort_field": "time_updated",
            },
        )
        resp.raise_for_status()
        projects = resp.json().get("result", {}).get("projects", []) or []
        for project in projects:
            draft = _project_to_draft(project)
            if draft is not None and draft.posted_at is not None:
                if draft.posted_at.timestamp() >= since_ts:
                    yield draft


def _project_to_draft(project: dict) -> RawItemDraft | None:
    pid = project.get("id")
    if pid is None:
        return None
    title = project.get("title") or ""
    body = project.get("description") or project.get("preview_description") or title
    if not body.strip():
        return None
    posted_at = None
    if project.get("time_submitted"):
        posted_at = datetime.fromtimestamp(project["time_submitted"], tz=UTC)
    seo_url = project.get("seo_url")
    url = f"https://www.freelancer.com/projects/{seo_url}" if seo_url else None
    budget = project.get("budget") or {}
    currency = project.get("currency") or {}
    return RawItemDraft(
        external_id=str(pid),
        body=body,
        title=title,
        url=url,
        author=None,  # the API does not expose the poster's username in the search result
        posted_at=posted_at,
        metrics={
            "budget_min": budget.get("minimum"),
            "budget_max": budget.get("maximum"),
            "currency": currency.get("code"),
            "bid_count": project.get("bid_stats", {}).get("bid_count"),
            "type": project.get("type"),  # 'fixed' | 'hourly'
        },
    )
