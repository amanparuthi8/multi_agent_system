"""
tests/test_workflows.py
Unit tests for the workflow execution engine (no live DB/MCP needed).
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from workflows.engine import (
    WorkflowContext,
    WorkflowEngine,
    WorkflowStep,
    StepStatus,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_ctx(name="test_workflow") -> WorkflowContext:
    return WorkflowContext(
        workflow_id="00000000-0000-0000-0000-000000000001",
        user_id="test_user",
        session_id="test_session",
        name=name,
    )


async def success_action(**kwargs):
    return {"status": "ok", "data": kwargs}


async def fail_action(**kwargs):
    raise RuntimeError("Simulated tool failure")


async def timeout_action(**kwargs):
    await asyncio.sleep(999)   # will be cut by timeout_sec=0.1


# ── Tests ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_step_success(monkeypatch):
    """A single successful step should complete the workflow."""
    monkeypatch.setattr(
        "workflows.engine.WorkflowEngine._persist_status",
        lambda *a, **kw: None,
    )
    ctx   = make_ctx()
    steps = [WorkflowStep(name="step1", action=success_action, args={"x": 1})]
    engine = WorkflowEngine(ctx, steps)
    result = await engine.run()

    assert result["status"] == "completed"
    assert result["steps"][0]["status"] == "completed"
    assert result["outputs"]["step1"]["data"]["x"] == 1


@pytest.mark.asyncio
async def test_retry_then_success(monkeypatch):
    """Step should retry on failure and succeed on second attempt."""
    monkeypatch.setattr(
        "workflows.engine.WorkflowEngine._persist_status",
        lambda *a, **kw: None,
    )
    call_count = {"n": 0}

    async def flaky(**kwargs):
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise RuntimeError("temporary failure")
        return {"status": "recovered"}

    ctx   = make_ctx()
    steps = [WorkflowStep(name="flaky_step", action=flaky, retry_limit=2)]
    engine = WorkflowEngine(ctx, steps)
    result = await engine.run()

    assert result["status"] == "completed"
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_permanent_failure(monkeypatch):
    """Step that always fails should mark workflow as failed."""
    monkeypatch.setattr(
        "workflows.engine.WorkflowEngine._persist_status",
        lambda *a, **kw: None,
    )
    ctx   = make_ctx()
    steps = [WorkflowStep(name="bad_step", action=fail_action, retry_limit=1)]
    engine = WorkflowEngine(ctx, steps)
    result = await engine.run()

    assert result["status"] == "failed"
    assert result["steps"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_dependency_skipped_on_failure(monkeypatch):
    """Dependent step should be skipped when its dependency fails."""
    monkeypatch.setattr(
        "workflows.engine.WorkflowEngine._persist_status",
        lambda *a, **kw: None,
    )
    ctx   = make_ctx()
    steps = [
        WorkflowStep(name="step1", action=fail_action, retry_limit=0),
        WorkflowStep(name="step2", action=success_action, depends_on=["step1"]),
    ]
    engine = WorkflowEngine(ctx, steps)
    result = await engine.run()

    statuses = {s["name"]: s["status"] for s in result["steps"]}
    assert statuses["step1"] == "failed"
    assert statuses["step2"] == "skipped"


@pytest.mark.asyncio
async def test_dollar_reference_resolution(monkeypatch):
    """$step_name.field references should resolve to prior step outputs."""
    monkeypatch.setattr(
        "workflows.engine.WorkflowEngine._persist_status",
        lambda *a, **kw: None,
    )

    async def producer(**kwargs):
        return {"task_id": "abc-123"}

    captured = {}

    async def consumer(linked_id, **kwargs):
        captured["linked_id"] = linked_id
        return {"status": "ok"}

    ctx   = make_ctx()
    steps = [
        WorkflowStep(name="produce", action=producer),
        WorkflowStep(
            name="consume",
            action=consumer,
            args={"linked_id": "$produce.task_id"},
            depends_on=["produce"],
        ),
    ]
    engine = WorkflowEngine(ctx, steps)
    await engine.run()

    assert captured["linked_id"] == "abc-123"


@pytest.mark.asyncio
async def test_timeout_triggers_failure(monkeypatch):
    """Steps that exceed timeout_sec should be marked failed."""
    monkeypatch.setattr(
        "workflows.engine.WorkflowEngine._persist_status",
        lambda *a, **kw: None,
    )
    ctx   = make_ctx()
    steps = [WorkflowStep(
        name="slow_step",
        action=timeout_action,
        timeout_sec=0.05,  # 50ms
        retry_limit=0,
    )]
    engine = WorkflowEngine(ctx, steps)
    result = await engine.run()

    assert result["steps"][0]["status"] == "failed"
    assert "Timed out" in result["steps"][0]["error"]


def test_topological_sort_cycle_detection():
    """Circular dependencies should raise ValueError."""
    ctx = make_ctx()
    steps = [
        WorkflowStep(name="a", action=success_action, depends_on=["b"]),
        WorkflowStep(name="b", action=success_action, depends_on=["a"]),
    ]
    engine = WorkflowEngine(ctx, steps)
    with pytest.raises(ValueError, match="Circular dependency"):
        engine._topological_sort()
