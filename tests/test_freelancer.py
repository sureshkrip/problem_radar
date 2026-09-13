from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pr.sources.freelancer import FreelancerSource

from .conftest import load_fixture, mock_client


@pytest.fixture
def single_freelancer_query(monkeypatch):
    cfg = {"freelancer": {"queries": ["automation"], "limit": 50}}
    import pr.sources.freelancer as freelancer

    monkeypatch.setattr(freelancer, "load_queries", lambda: cfg)
    return cfg


def test_freelancer_maps_projects_and_budget(single_freelancer_query):
    client = mock_client(load_fixture("freelancer_active.json"))
    src = FreelancerSource(client=client)
    drafts = list(src.fetch(datetime(2024, 1, 1, tzinfo=UTC)))

    # The 2020 project is dropped by the since window; only the recent one survives.
    assert len(drafts) == 1
    d = drafts[0]
    assert d.external_id == "111"
    assert d.title.startswith("Automate invoice")
    assert d.url == "https://www.freelancer.com/projects/automate-invoice-data-entry-111"
    # The posted budget is the willingness-to-pay signal (spec §2).
    assert d.metrics["budget_min"] == 250
    assert d.metrics["budget_max"] == 750
    assert d.metrics["currency"] == "USD"
    assert d.metrics["bid_count"] == 14


def test_freelancer_since_filters_everything(single_freelancer_query):
    client = mock_client(load_fixture("freelancer_active.json"))
    src = FreelancerSource(client=client)
    drafts = list(src.fetch(datetime(2025, 1, 1, tzinfo=UTC)))
    assert drafts == []
