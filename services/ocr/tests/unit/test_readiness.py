"""Tests for the OCR /health/ready endpoint."""

import pytest
from fastapi.testclient import TestClient

from app import config as config_module
from app.main import app


@pytest.fixture
def clear_settings_cache():
    config_module.get_settings.cache_clear()
    yield
    config_module.get_settings.cache_clear()


def test_health_is_always_200(clear_settings_cache):
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"


def test_ready_mock_mode_returns_ready(monkeypatch, clear_settings_cache):
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    with TestClient(app) as client:
        r = client.get("/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["mode"] == "mock"
        assert body["checks"]["mock_mode"] is True


def test_ready_missing_credentials_returns_503(monkeypatch, clear_settings_cache):
    """With mock mode off and a bogus credentials path, readiness fails."""
    monkeypatch.delenv("OCR_MOCK_MODE", raising=False)
    monkeypatch.setenv("OCR_GOOGLE_CREDENTIALS_PATH", "/nowhere/does_not_exist.json")
    with TestClient(app) as client:
        r = client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["google_credentials"]["ok"] is False
        assert "not found" in body["checks"]["google_credentials"]["error"]
