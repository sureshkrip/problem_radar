"""App-store review source — the "existing tool people hate" signal (spec §2).

Two backends, both filtered to 1–2 star reviews:

* **Apple** — the public RSS customer-reviews feed, one per app id, no auth. Walked over httpx
  so it is fixture-testable with no network (spec §13). URL shape:
  `https://itunes.apple.com/{country}/rss/customerreviews/page={n}/id={app_id}/sortby=mostrecent/json`
* **Google Play** — the `google-play-scraper` package (spec §2). It does its own HTTP and is not
  injectable, so it is imported lazily and only exercised when `play_package_names` is configured;
  a missing package or a fetch error is logged and skipped rather than failing the whole run.

Star rating lands in `metrics` (star_rating) so scoring can read it as a pain / willingness signal.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx

from ..config import load_queries
from ..models import RawItemDraft
from .base import Source

APPLE_FEED = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "page={page}/id={app_id}/sortby=mostrecent/json"
)
POLITE_DELAY_S = 1.0
DEFAULT_STAR_MAX = 2


class AppStoreSource(Source):
    slug = "appstore"

    def _client_or_default(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=30.0, headers={"User-Agent": "problem-radar/0.1"})

    def fetch(self, since: datetime) -> Iterator[RawItemDraft]:
        cfg = load_queries()
        a_cfg = cfg.get("appstore") or {}
        apple_ids = a_cfg.get("apple_app_ids") or []
        play_names = a_cfg.get("play_package_names") or []
        country = a_cfg.get("country", "us")
        max_pages = int(a_cfg.get("max_pages", 3))
        star_max = int(a_cfg.get("star_max", DEFAULT_STAR_MAX))
        since_ts = since.timestamp()

        client = self._client_or_default()
        owns_client = self._client is None
        try:
            for app_id in apple_ids:
                yield from self._apple(
                    client, str(app_id), country, max_pages, star_max, since_ts,
                    polite=owns_client,
                )
        finally:
            if owns_client:
                client.close()

        for pkg in play_names:
            yield from _play(str(pkg), country, star_max, since_ts)

    def _apple(
        self,
        client: httpx.Client,
        app_id: str,
        country: str,
        max_pages: int,
        star_max: int,
        since_ts: float,
        polite: bool,
    ) -> Iterator[RawItemDraft]:
        for page in range(1, max_pages + 1):
            url = APPLE_FEED.format(country=country, page=page, app_id=app_id)
            resp = client.get(url)
            resp.raise_for_status()
            entries = resp.json().get("feed", {}).get("entry", []) or []
            # The first entry is app metadata (it has no im:rating); reviews follow.
            reviews = [e for e in entries if "im:rating" in e]
            if not reviews:
                break
            for entry in reviews:
                draft = _apple_entry_to_draft(entry, app_id, star_max, since_ts)
                if draft is not None:
                    yield draft
            if polite:
                time.sleep(POLITE_DELAY_S)


def _apple_entry_to_draft(
    entry: dict, app_id: str, star_max: int, since_ts: float
) -> RawItemDraft | None:
    try:
        rating = int(entry.get("im:rating", {}).get("label", "0"))
    except (TypeError, ValueError):
        return None
    if rating < 1 or rating > star_max:
        return None
    review_id = entry.get("id", {}).get("label")
    if not review_id:
        return None
    title = entry.get("title", {}).get("label") or ""
    content = entry.get("content", {}).get("label") or ""
    body = f"{title}\n{content}".strip() or title
    if not body.strip():
        return None
    posted_at = _parse_iso(entry.get("updated", {}).get("label"))
    if posted_at is not None and posted_at.timestamp() < since_ts:
        return None
    author = entry.get("author", {}).get("name", {}).get("label")
    return RawItemDraft(
        external_id=f"apple:{review_id}",
        body=content or title,
        title=title,
        url=entry.get("author", {}).get("uri", {}).get("label"),
        author=author,
        posted_at=posted_at,
        metrics={
            "store": "apple",
            "app_id": app_id,
            "star_rating": rating,
            "app_version": entry.get("im:version", {}).get("label"),
        },
    )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _play(pkg: str, country: str, star_max: int, since_ts: float) -> Iterator[RawItemDraft]:
    """Yield low-star Play reviews via google-play-scraper. Lazy + best-effort (see module doc)."""
    try:
        from google_play_scraper import Sort, reviews
    except ImportError:
        return
    try:
        results, _ = reviews(
            pkg, lang="en", country=country, sort=Sort.NEWEST, count=100
        )
    except Exception:  # a scrape failure must not sink the whole ingest run
        return
    for r in results:
        rating = r.get("score")
        if not rating or rating > star_max:
            continue
        posted_at = r.get("at")
        if isinstance(posted_at, datetime):
            posted_at = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=UTC)
            if posted_at.timestamp() < since_ts:
                continue
        else:
            posted_at = None
        content = r.get("content") or ""
        if not content.strip():
            continue
        yield RawItemDraft(
            external_id=f"play:{r.get('reviewId')}",
            body=content,
            title=None,
            url=None,
            author=r.get("userName"),
            posted_at=posted_at,
            metrics={
                "store": "play",
                "app_id": pkg,
                "star_rating": rating,
                "app_version": r.get("reviewCreatedVersion"),
            },
        )
