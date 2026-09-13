from __future__ import annotations

from fastapi.testclient import TestClient

from pr import config
from pr.sources import clip
from pr.web.app import _bookmarklet, app


def test_build_draft_is_content_addressed():
    a = clip.build_draft(source_label="g2", url="https://g2.com/x", text="  hate this tool  ")
    b = clip.build_draft(source_label="g2", url="https://g2.com/x", text="hate this tool")
    # Same url+text => same external_id => idempotent re-clip (body is stripped first).
    assert a.external_id == b.external_id
    assert a.body == "hate this tool"
    assert a.metrics["source_label"] == "g2"
    assert a.metrics["manual"] is True

    c = clip.build_draft(source_label="g2", url="https://g2.com/y", text="hate this tool")
    assert c.external_id != a.external_id  # different url => different id


def test_bookmarklet_targets_the_clip_endpoint():
    bm = _bookmarklet("https://radar.example/clip")
    assert bm.startswith("javascript:")
    assert "https://radar.example/clip" in bm
    assert "document.title" in bm and "location.href" in bm


def test_clip_page_renders_in_dev(monkeypatch):
    # GET /clip touches no database, so it renders even without a DB configured.
    monkeypatch.delenv("RADAR_BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("RADAR_BASIC_AUTH_PASS", raising=False)
    config.get_settings.cache_clear()
    try:
        resp = TestClient(app).get("/clip")
        assert resp.status_code == 200
        assert "Manual capture" in resp.text
        assert "javascript:" in resp.text  # the bookmarklet href
    finally:
        config.get_settings.cache_clear()
