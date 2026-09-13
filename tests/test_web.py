from __future__ import annotations

from fastapi.testclient import TestClient

from pr import config
from pr.web.app import app


def test_healthz_is_open():
    # /healthz has no auth dependency — always reachable for Coolify's healthcheck.
    assert TestClient(app).get("/healthz").text == "ok"


def test_healthz_open_even_when_auth_configured(monkeypatch):
    monkeypatch.setenv("RADAR_BASIC_AUTH_USER", "u")
    monkeypatch.setenv("RADAR_BASIC_AUTH_PASS", "p")
    config.get_settings.cache_clear()
    try:
        assert TestClient(app).get("/healthz").status_code == 200
    finally:
        config.get_settings.cache_clear()


def test_auth_required_when_configured(monkeypatch):
    monkeypatch.setenv("RADAR_BASIC_AUTH_USER", "u")
    monkeypatch.setenv("RADAR_BASIC_AUTH_PASS", "p")
    config.get_settings.cache_clear()
    try:
        client = TestClient(app)
        # auth runs as a dependency before the handler touches the DB, so these 401
        # without any database connection.
        assert client.get("/").status_code == 401
        assert client.get("/", auth=("u", "wrong")).status_code == 401
    finally:
        config.get_settings.cache_clear()


def test_no_auth_in_dev_mode(monkeypatch):
    # With no credentials configured, the gate is open (local dev). Reaching the DB would
    # error, so we only assert it is NOT a 401 — i.e. auth did not block the request.
    monkeypatch.delenv("RADAR_BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("RADAR_BASIC_AUTH_PASS", raising=False)
    config.get_settings.cache_clear()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        assert client.get("/").status_code != 401
    finally:
        config.get_settings.cache_clear()
