from __future__ import annotations

from pr.models import RawItemDraft
from pr.pipeline.filter import is_noise, keep


def _draft(body: str, title: str | None = None) -> RawItemDraft:
    return RawItemDraft(external_id="x", body=body, title=title)


def test_keeps_genuine_problem():
    d = _draft("I keep doing tenant screening manually in spreadsheets and it is painful.")
    assert is_noise(d) is False


def test_drops_hiring_spam():
    assert is_noise(_draft("We're hiring a senior Python engineer, apply now!")) is True
    assert is_noise(_draft("[HIRING] Remote backend role, salary range attached.")) is True


def test_drops_self_promo():
    assert is_noise(_draft("Show HN: I built a tool that reconciles invoices for you")) is True
    assert is_noise(_draft("Check out my new app, use my referral for a discount code")) is True


def test_drops_too_short():
    assert is_noise(_draft("thanks!")) is True


def test_keep_filters_list():
    drafts = [
        _draft("I wish there was a way to automate landlord paperwork without spreadsheets."),
        _draft("We are hiring! apply now for our sales team."),
    ]
    survivors = keep(drafts)
    assert len(survivors) == 1
    assert "landlord" in survivors[0].body
