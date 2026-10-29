"""Smoke tests for the web app. Never calls the real Claude API."""

import pytest
from fastapi.testclient import TestClient

import app as webapp


@pytest.fixture
def client():
    with TestClient(webapp.app) as c:  # context manager runs the lifespan (MCP session)
        yield c


def test_index_serves_page(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Why did this fail?" in r.text


def test_complete_suggests_logs(client):
    r = client.get("/api/complete", params={"value": "ap"})
    assert r.status_code == 200
    assert "app.log" in r.json()["values"]


def test_run_requires_log_file(client, monkeypatch):
    async def fail(*args, **kwargs):
        raise AssertionError("Claude API must not be called")

    monkeypatch.setattr(webapp.claude.messages, "create", fail)
    r = client.post("/api/run", json={"log_file": "  "})
    assert r.status_code == 400
