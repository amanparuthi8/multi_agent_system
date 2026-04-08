"""
tests/test_api.py
FastAPI integration tests using httpx TestClient.
Database and MCP are mocked — no live infra needed for CI.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch
from httpx import AsyncClient, ASGITransport


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db(monkeypatch):
    """Patch db_session to avoid real AlloyDB connections."""
    from unittest.mock import MagicMock, patch
    from contextlib import contextmanager

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    mock_session.query.return_value.filter.return_value.count.return_value = 0
    mock_session.query.return_value.filter.return_value.all.return_value = []

    @contextmanager
    def _mock_db_session():
        yield mock_session

    monkeypatch.setattr("database.connection.db_session", _mock_db_session)
    return mock_session


@pytest.fixture
def mock_mcp(monkeypatch):
    """Patch MCP health check and tool loading."""
    monkeypatch.setattr("tools.mcp_tools.health_check", lambda: True)
    monkeypatch.setattr("tools.mcp_tools.load_task_tools", lambda: [])
    monkeypatch.setattr("tools.mcp_tools.load_calendar_tools", lambda: [])
    monkeypatch.setattr("tools.mcp_tools.load_knowledge_tools", lambda: [])
    monkeypatch.setattr("tools.mcp_tools.load_memory_tools", lambda: [])
    monkeypatch.setattr("tools.mcp_tools.load_all_tools", lambda: [])


@pytest.fixture
async def client(mock_db, mock_mcp):
    """Async test client for the FastAPI app."""
    from api.main import app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Health endpoint ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "model" in data


@pytest.mark.asyncio
async def test_root_endpoint(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "service" in resp.json()


# ── Task endpoints ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_tasks_empty(client, mock_db):
    resp = await client.get("/api/v1/tasks/?user_id=test_user")
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert body["items"] == []


@pytest.mark.asyncio
async def test_create_task(client, mock_db):
    from unittest.mock import MagicMock
    import uuid
    from datetime import datetime

    mock_task = MagicMock()
    mock_task.to_dict.return_value = {
        "task_id":     str(uuid.uuid4()),
        "user_id":     "test_user",
        "title":       "Test Task",
        "description": None,
        "status":      "pending",
        "priority":    "medium",
        "due_date":    None,
        "tags":        [],
        "metadata":    {},
        "created_at":  datetime.utcnow().isoformat(),
        "updated_at":  datetime.utcnow().isoformat(),
    }
    mock_db.add.return_value = None
    mock_db.flush.return_value = None

    with patch("api.routers.tasks.Task", return_value=mock_task):
        resp = await client.post("/api/v1/tasks/", json={
            "user_id":  "test_user",
            "title":    "Test Task",
            "priority": "medium",
        })
    assert resp.status_code == 201


# ── Event endpoints ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_events_empty(client, mock_db):
    resp = await client.get("/api/v1/events/?user_id=test_user")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ── Workflow endpoints ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trigger_workflow_returns_202(client, mock_db):
    resp = await client.post("/api/v1/workflows/trigger", json={
        "user_id":    "test_user",
        "name":       "plan_week",
        "params":     {},
        "session_id": "sess-001",
    })
    assert resp.status_code == 202
    body = resp.json()
    assert "workflow_id" in body
    assert body["status"] == "running"


@pytest.mark.asyncio
async def test_get_workflow_not_found(client, mock_db):
    resp = await client.get("/api/v1/workflows/00000000-0000-0000-0000-000000000099")
    assert resp.status_code == 404


# ── Request ID middleware ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_request_id_header_present(client):
    resp = await client.get("/health")
    assert "x-request-id" in resp.headers
    assert "x-response-time" in resp.headers
