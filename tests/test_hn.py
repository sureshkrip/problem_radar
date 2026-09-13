from __future__ import annotations

from datetime import UTC, datetime

from pr.sources.hn import HackerNewsSource

from .conftest import load_fixture, mock_client


def test_hn_fetch_maps_hits(single_query):
    client = mock_client(load_fixture("hn_search.json"))
    src = HackerNewsSource(client=client)
    drafts = list(src.fetch(datetime(2024, 1, 1, tzinfo=UTC)))

    # Third hit has an empty body and must be dropped; one phrase, one page => 2 drafts.
    assert len(drafts) == 2

    story = next(d for d in drafts if d.external_id == "111")
    assert story.author == "alice"
    assert "reconciling invoices" in story.body
    assert story.url == "https://news.ycombinator.com/item?id=111"  # null url -> item link
    assert story.posted_at == datetime.fromtimestamp(1725000000, tz=UTC)
    assert story.metrics["points"] == 42

    comment = next(d for d in drafts if d.external_id == "222")
    assert "small landlords" in comment.body  # comment_text used as body
