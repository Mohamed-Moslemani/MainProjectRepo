"""Tests for the Face /health/ready endpoint."""

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
    monkeypatch.setenv("FACE_MOCK_MODE", "true")
    with TestClient(app) as client:
        r = client.get("/health/ready")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ready"
        assert body["mode"] == "mock"
        assert body["checks"]["mock_mode"] is True


def test_ready_missing_aws_keys_returns_503(monkeypatch, clear_settings_cache):
    """With mock mode off and empty AWS creds, readiness fails before
    any boto3 call is attempted."""
    monkeypatch.delenv("FACE_MOCK_MODE", raising=False)
    monkeypatch.setenv("FACE_AWS_ACCESS_KEY_ID", "")
    monkeypatch.setenv("FACE_AWS_SECRET_ACCESS_KEY", "")
    with TestClient(app) as client:
        r = client.get("/health/ready")
        assert r.status_code == 503
        body = r.json()
        assert body["status"] == "not_ready"
        assert body["checks"]["aws_credentials"]["ok"] is False
