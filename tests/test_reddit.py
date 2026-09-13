from __future__ import annotations

from datetime import UTC, datetime

from pr.sources.reddit import RedditSource

from .conftest import load_fixture, mock_client


def test_reddit_fetch_maps_children(single_query):
    client = mock_client(load_fixture("reddit_search.json"))
    src = RedditSource(client=client)
    drafts = list(src.fetch(datetime(2024, 1, 1, tzinfo=UTC)))

    # The t1 comment is ignored; one sub, one phrase => 2 t3 posts.
    assert len(drafts) == 2

    post = next(d for d in drafts if d.external_id == "abc123")
    assert post.author == "dave"
    assert post.title.startswith("How do you all handle")
    assert post.url == "https://www.reddit.com/r/Landlord/comments/abc123/how_do_you_all_handle/"
    assert post.metrics["subreddit"] == "Landlord"
    assert post.metrics["ups"] == 57

    # Empty selftext falls back to the title as body.
    linkpost = next(d for d in drafts if d.external_id == "def456")
    assert linkpost.body == linkpost.title


def test_reddit_since_filters_old_posts(single_query):
    client = mock_client(load_fixture("reddit_search.json"))
    src = RedditSource(client=client)
    # since after both posts' created_utc (1725100000 == 2024-08-31) => nothing survives.
    drafts = list(src.fetch(datetime(2025, 1, 1, tzinfo=UTC)))
    assert drafts == []
