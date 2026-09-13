from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pr.sources.appstore import AppStoreSource

from .conftest import load_fixture, mock_client


@pytest.fixture
def one_apple_app(monkeypatch):
    cfg = {
        "appstore": {
            "apple_app_ids": ["284882215"],
            "play_package_names": [],
            "country": "us",
            "star_max": 2,
            "max_pages": 1,
        }
    }
    import pr.sources.appstore as appstore

    monkeypatch.setattr(appstore, "load_queries", lambda: cfg)
    return cfg


def test_appstore_keeps_only_low_star_reviews(one_apple_app):
    client = mock_client(load_fixture("appstore_reviews.json"))
    src = AppStoreSource(client=client)
    drafts = list(src.fetch(datetime(2024, 1, 1, tzinfo=UTC)))

    # The app-metadata entry (no rating) and the 5-star review are dropped; two survive.
    assert len(drafts) == 2
    ids = {d.external_id for d in drafts}
    assert ids == {"apple:9001", "apple:9002"}
    for d in drafts:
        assert d.metrics["store"] == "apple"
        assert d.metrics["star_rating"] <= 2
        assert d.metrics["app_id"] == "284882215"

    one = next(d for d in drafts if d.external_id == "apple:9001")
    assert one.author == "annoyed_user"
    assert one.metrics["star_rating"] == 1


def test_appstore_since_filters_old_reviews(one_apple_app):
    client = mock_client(load_fixture("appstore_reviews.json"))
    src = AppStoreSource(client=client)
    drafts = list(src.fetch(datetime(2025, 1, 1, tzinfo=UTC)))
    assert drafts == []
