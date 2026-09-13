"""Reddit source via the official API (OAuth2 client-credentials, "script" app).

Auth: POST https://www.reddit.com/api/v1/access_token with HTTP basic auth
(client_id:client_secret) and grant_type=client_credentials. A descriptive User-Agent is
mandatory or Reddit returns 429s.

Search: GET https://oauth.reddit.com/r/{sub}/search with restrict_sr=1&sort=new. We search
each configured phrase within each curated subreddit and keep items posted at/after `since`.

Note (spec §13): the Reddit API is unreachable from some sandboxes. Client is written against
recorded fixtures; verify live ingest on the deploy box.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from ..config import get_settings, load_queries
from ..models import RawItemDraft
from .base import Source

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
POLITE_DELAY_S = 1.0


class RedditSource(Source):
    slug = "reddit"

    def fetch(self, since: datetime) -> Iterator[RawItemDraft]:
        cfg = load_queries()
        r_cfg = cfg.get("reddit") or {}
        subreddits = r_cfg.get("subreddits") or []
        phrases = r_cfg.get("phrases") or cfg.get("phrases") or []
        limit = int(r_cfg.get("limit", 50))
        since_ts = since.timestamp()

        client = self._client
        owns_client = client is None
        if client is None:
            client = self._build_authed_client()
        try:
            for sub in subreddits:
                for phrase in phrases:
                    yield from self._search(client, sub, phrase, limit, since_ts)
                    if owns_client:
                        time.sleep(POLITE_DELAY_S)
        finally:
            if owns_client:
                client.close()

    def _build_authed_client(self) -> httpx.Client:
        settings = get_settings()
        if not settings.reddit_client_id or not settings.reddit_client_secret:
            raise RuntimeError(
                "REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not set — cannot authenticate."
            )
        headers = {"User-Agent": settings.reddit_user_agent}
        token = _fetch_token(settings, headers)
        return httpx.Client(
            base_url=API_BASE,
            timeout=30.0,
            headers={**headers, "Authorization": f"bearer {token}"},
        )

    def _search(
        self,
        client: httpx.Client,
        sub: str,
        phrase: str,
        limit: int,
        since_ts: float,
    ) -> Iterator[RawItemDraft]:
        resp = client.get(
            f"/r/{sub}/search",
            params={
                "q": phrase,
                "restrict_sr": 1,
                "sort": "new",
                "limit": limit,
            },
        )
        resp.raise_for_status()
        children = resp.json().get("data", {}).get("children", [])
        for child in children:
            draft = _child_to_draft(child, sub)
            if draft is not None and draft.posted_at is not None:
                if draft.posted_at.timestamp() >= since_ts:
                    yield draft


def _fetch_token(settings, headers: dict) -> str:
    resp = httpx.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(settings.reddit_client_id, settings.reddit_client_secret),
        headers=headers,
        timeout=30.0,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _child_to_draft(child: dict, sub: str) -> RawItemDraft | None:
    if child.get("kind") != "t3":  # only link/self posts, not comments
        return None
    data = child.get("data", {})
    ext_id = data.get("id")
    if not ext_id:
        return None
    title = data.get("title") or ""
    body = data.get("selftext") or title
    if not body.strip():
        return None
    posted_at = None
    if data.get("created_utc"):
        posted_at = datetime.fromtimestamp(data["created_utc"], tz=UTC)
    permalink = data.get("permalink")
    url = f"https://www.reddit.com{permalink}" if permalink else data.get("url")
    return RawItemDraft(
        external_id=ext_id,
        body=body,
        title=title,
        url=url,
        author=data.get("author"),
        posted_at=posted_at,
        metrics={
            "ups": data.get("ups"),
            "num_comments": data.get("num_comments"),
            "subreddit": data.get("subreddit") or sub,
            "over_18": data.get("over_18"),
        },
    )
