"""
api/routers/workflows.py
REST endpoints for workflow execution and status inspection.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel

from database.connection import db_session
from database.models import Workflow

router = APIRouter()


class WorkflowTriggerRequest(BaseModel):
    user_id:    str
    session_id: str = ""
    name:       str
    # workflow-specific parameters passed as freeform dict
    params:     dict = {}


@router.post("/trigger", status_code=202)
async def trigger_workflow(
    body: WorkflowTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """
    Trigger a named workflow asynchronously.
    Supported workflow names:
      • meeting_with_task  — schedule meeting + follow-up task
      • plan_week          — weekly planning across tasks + events + notes
    Returns workflow_id immediately; poll /workflows/{id} for status.
    """
    workflow_id = str(uuid.uuid4())

    # Persist initial record
    with db_session() as db:
        wf = Workflow(
            workflow_id=uuid.UUID(workflow_id),
            user_id=body.user_id,
            name=body.name,
            status="running",
            steps=[],
        )
        db.add(wf)

    # Run the actual workflow in a background task
    background_tasks.add_task(
        _run_workflow_background,
        workflow_id=workflow_id,
        user_id=body.user_id,
        session_id=body.session_id or str(uuid.uuid4()),
        name=body.name,
        params=body.params,
    )

    return {
        "workflow_id": workflow_id,
        "status":      "running",
        "message":     f"Workflow '{body.name}' started. Poll /api/v1/workflows/{workflow_id} for updates.",
    }


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str):
    with db_session() as db:
        wf = db.query(Workflow).filter(
            Workflow.workflow_id == uuid.UUID(workflow_id)
        ).first()
        if not wf:
            raise HTTPException(status_code=404, detail="Workflow not found")
        return wf.to_dict()


@router.get("/")
def list_workflows(user_id: str, status: Optional[str] = None):
    with db_session() as db:
        q = db.query(Workflow).filter(Workflow.user_id == user_id)
        if status:
            q = q.filter(Workflow.status == status)
        wfs = q.order_by(Workflow.started_at.desc()).limit(20).all()
        return {"items": [w.to_dict() for w in wfs]}


# ── Background workflow runner ─────────────────────────────────────────────────

async def _run_workflow_background(
    workflow_id: str,
    user_id:     str,
    session_id:  str,
    name:        str,
    params:      dict,
):
    """
    Dispatches to the correct workflow engine factory based on name.
    All errors are caught and persisted — never crash the API process.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        from workflows.engine import WorkflowContext

        ctx = WorkflowContext(
            workflow_id=workflow_id,
            user_id=user_id,
            session_id=session_id,
            name=name,
        )

        if name == "meeting_with_task":
            await _run_meeting_with_task(ctx, params)
        elif name == "plan_week":
            await _run_plan_week(ctx, params)
        else:
            raise ValueError(f"Unknown workflow name: '{name}'. "
                             "Valid options: meeting_with_task, plan_week")

    except Exception as exc:
        logger.error("Background workflow %s failed: %s", workflow_id, exc, exc_info=True)
        with db_session() as db:
            wf = db.query(Workflow).filter(
                Workflow.workflow_id == uuid.UUID(workflow_id)
            ).first()
            if wf:
                wf.status = "failed"
                wf.error  = str(exc)


async def _run_meeting_with_task(ctx, params: dict):
    """Wires up the meeting_with_task workflow engine."""
    from tools.mcp_tools import _get_client

    client = _get_client()
    toolset = client.load_toolset("full_toolset")

    # Extract callable tools by name
    tool_map = {t.name: t for t in toolset}

    from workflows.engine import make_meeting_with_task_workflow

    engine = make_meeting_with_task_workflow(
        ctx=ctx,
        schedule_fn=tool_map["schedule_event"].__call__,
        create_task_fn=tool_map["create_task"].__call__,
        conflict_fn=tool_map["check_conflicts"].__call__,
        create_note_fn=tool_map["create_note"].__call__,
        meeting_args={
            "title":       params.get("meeting_title", "Team Meeting"),
            "description": params.get("meeting_description", ""),
            "start_time":  params["start_time"],
            "end_time":    params["end_time"],
            "location":    params.get("location", ""),
            "attendees":   params.get("attendees", ""),
            "linked_task_id": "",
        },
        task_title=params.get("task_title", f"Follow up: {params.get('meeting_title', 'Meeting')}"),
        note_content=params.get("agenda"),
    )
    await engine.run()


async def _run_plan_week(ctx, params: dict):
    """Simple plan_week: list tasks + events, save a planning note."""
    import asyncio
    from tools.mcp_tools import _get_client
    from datetime import datetime, timedelta

    now       = datetime.utcnow()
    week_end  = now + timedelta(days=7)
    client    = _get_client()
    toolset   = client.load_toolset("full_toolset")
    tool_map  = {t.name: t for t in toolset}

    from workflows.engine import WorkflowEngine, WorkflowStep

    steps = [
        WorkflowStep(
            name="list_tasks",
            action=tool_map["list_tasks"].__call__,
            args={
                "user_id":       ctx.user_id,
                "status_filter": "pending",
            },
        ),
        WorkflowStep(
            name="list_events",
            action=tool_map["list_events"].__call__,
            args={
                "user_id":   ctx.user_id,
                "from_time": now.isoformat(),
                "to_time":   week_end.isoformat(),
            },
        ),
        WorkflowStep(
            name="save_weekly_plan",
            action=tool_map["create_note"].__call__,
            args={
                "user_id": ctx.user_id,
                "title":   f"Weekly Plan — {now.strftime('%Y-%m-%d')}",
                "content": "Auto-generated weekly plan. See tasks and events.",
                "tags":    "planning,weekly",
            },
            depends_on=["list_tasks", "list_events"],
        ),
    ]

    engine = WorkflowEngine(ctx, steps)
    await engine.run()
