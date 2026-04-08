"""
workflows/engine.py
Workflow Execution Engine — wraps ADK agent calls with:
  • Planning → Execution → Validation loop
  • Conditional branching
  • Retry with exponential back-off
  • Persistent workflow state in AlloyDB
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from database.connection import db_session
from database.models import Workflow

logger = logging.getLogger(__name__)


class StepStatus(str, Enum):
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    SKIPPED   = "skipped"
    RETRYING  = "retrying"


@dataclass
class WorkflowStep:
    name:         str
    action:       Callable[..., Any]     # async callable
    args:         dict    = field(default_factory=dict)
    depends_on:   list[str] = field(default_factory=list)  # step names
    retry_limit:  int    = 2
    timeout_sec:  float  = 30.0
    # filled at runtime
    status:       StepStatus = StepStatus.PENDING
    result:       Any        = None
    error:        str | None = None
    attempts:     int        = 0


@dataclass
class WorkflowContext:
    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id:     str = "default_user"
    session_id:  str = ""
    name:        str = "unnamed_workflow"
    # step results keyed by step name — allows inter-step data passing
    outputs:     dict[str, Any] = field(default_factory=dict)


class WorkflowEngine:
    """
    Executes a sequence of WorkflowSteps with dependency resolution,
    retry logic, and persists state to AlloyDB after each step.
    """

    def __init__(self, ctx: WorkflowContext, steps: list[WorkflowStep]) -> None:
        self.ctx   = ctx
        self.steps = {s.name: s for s in steps}

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self) -> dict:
        """
        Execute all steps respecting dependency order.
        Returns final workflow result dict.
        """
        logger.info("[Workflow %s] Starting '%s'", self.ctx.workflow_id, self.ctx.name)
        self._persist_status("running")

        execution_order = self._topological_sort()

        for step_name in execution_order:
            step = self.steps[step_name]

            # ── Check if dependencies succeeded ──────────────────────────────
            if not self._deps_met(step):
                step.status = StepStatus.SKIPPED
                step.error  = "Dependency failed — step skipped"
                logger.warning("[Workflow %s] Skipping '%s' (dep failure)", self.ctx.workflow_id, step_name)
                self._persist_status("running")
                continue

            # ── Execute with retry ────────────────────────────────────────────
            await self._execute_step(step)
            self._persist_status("running")

            if step.status == StepStatus.COMPLETED:
                self.ctx.outputs[step_name] = step.result

        # ── Final status ──────────────────────────────────────────────────────
        final_status = self._compute_final_status()
        result = {
            "workflow_id": self.ctx.workflow_id,
            "status":      final_status,
            "steps":       self._steps_summary(),
            "outputs":     self.ctx.outputs,
        }
        self._persist_status(final_status, result=result)
        logger.info(
            "[Workflow %s] Finished with status=%s",
            self.ctx.workflow_id, final_status,
        )
        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _execute_step(self, step: WorkflowStep) -> None:
        """Run one step with timeout + exponential back-off retry."""
        step.status = StepStatus.RUNNING
        backoff = 1.0

        while step.attempts <= step.retry_limit:
            step.attempts += 1
            try:
                step.result = await asyncio.wait_for(
                    step.action(**self._resolve_args(step)),
                    timeout=step.timeout_sec,
                )
                step.status = StepStatus.COMPLETED
                step.error  = None
                logger.info(
                    "[Workflow %s] Step '%s' completed (attempt %d)",
                    self.ctx.workflow_id, step.name, step.attempts,
                )
                return

            except asyncio.TimeoutError:
                step.error = f"Timed out after {step.timeout_sec}s"
                logger.warning(
                    "[Workflow %s] Step '%s' timeout (attempt %d)",
                    self.ctx.workflow_id, step.name, step.attempts,
                )
            except Exception as exc:
                step.error = str(exc)
                logger.warning(
                    "[Workflow %s] Step '%s' failed: %s (attempt %d)",
                    self.ctx.workflow_id, step.name, exc, step.attempts,
                )

            if step.attempts <= step.retry_limit:
                step.status = StepStatus.RETRYING
                await asyncio.sleep(backoff)
                backoff *= 2        # exponential back-off
            else:
                step.status = StepStatus.FAILED
                logger.error(
                    "[Workflow %s] Step '%s' permanently failed after %d attempts",
                    self.ctx.workflow_id, step.name, step.attempts,
                )

    def _resolve_args(self, step: WorkflowStep) -> dict:
        """
        Merge static step.args with dynamic outputs from dependency steps.
        A step can reference a dependency's output via "$dep_name.field" notation.
        """
        resolved = dict(step.args)
        for key, val in resolved.items():
            if isinstance(val, str) and val.startswith("$"):
                # e.g.  "$create_task.task_id"
                parts = val.lstrip("$").split(".", 1)
                dep_name, field_path = parts[0], (parts[1] if len(parts) > 1 else None)
                dep_output = self.ctx.outputs.get(dep_name, {})
                resolved[key] = (
                    dep_output.get(field_path) if field_path else dep_output
                )
        return resolved

    def _deps_met(self, step: WorkflowStep) -> bool:
        return all(
            self.steps[dep].status == StepStatus.COMPLETED
            for dep in step.depends_on
            if dep in self.steps
        )

    def _topological_sort(self) -> list[str]:
        """Kahn's algorithm — returns step names in safe execution order."""
        in_degree = {name: 0 for name in self.steps}
        adj: dict[str, list[str]] = {name: [] for name in self.steps}

        for name, step in self.steps.items():
            for dep in step.depends_on:
                if dep in self.steps:
                    adj[dep].append(name)
                    in_degree[name] += 1

        queue = [n for n, d in in_degree.items() if d == 0]
        order = []
        while queue:
            n = queue.pop(0)
            order.append(n)
            for neighbour in adj[n]:
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        if len(order) != len(self.steps):
            raise ValueError("Circular dependency detected in workflow steps")
        return order

    def _compute_final_status(self) -> str:
        statuses = {s.status for s in self.steps.values()}
        if StepStatus.FAILED in statuses:
            return "failed" if StepStatus.COMPLETED not in statuses else "partial"
        return "completed"

    def _steps_summary(self) -> list[dict]:
        return [
            {
                "name":     s.name,
                "status":   s.status.value,
                "attempts": s.attempts,
                "result":   s.result,
                "error":    s.error,
            }
            for s in self.steps.values()
        ]

    def _persist_status(self, status: str, result: dict | None = None) -> None:
        """Write workflow state to AlloyDB after each step."""
        try:
            with db_session() as session:
                wf = session.query(Workflow).filter_by(
                    workflow_id=self.ctx.workflow_id
                ).first()

                if wf is None:
                    wf = Workflow(
                        workflow_id=uuid.UUID(self.ctx.workflow_id),
                        user_id=self.ctx.user_id,
                        name=self.ctx.name,
                    )
                    session.add(wf)

                wf.status = status
                wf.steps  = self._steps_summary()
                if result:
                    wf.result = result
                if status in ("completed", "failed", "partial"):
                    wf.finished_at = datetime.utcnow()
        except Exception as exc:
            # Persistence failure must NOT crash the workflow
            logger.error("Failed to persist workflow state: %s", exc)


# ── Convenience factory for common workflows ──────────────────────────────────

def make_meeting_with_task_workflow(
    ctx: WorkflowContext,
    schedule_fn: Callable,
    create_task_fn: Callable,
    conflict_fn: Callable,
    create_note_fn: Callable,
    meeting_args: dict,
    task_title: str,
    note_content: str | None = None,
) -> WorkflowEngine:
    """
    Pre-built workflow: "Schedule meeting → follow-up task → agenda note"
    Demonstrates inter-step dependency via $-reference syntax.
    """
    steps = [
        WorkflowStep(
            name="check_conflicts",
            action=conflict_fn,
            args={
                "user_id":    ctx.user_id,
                "start_time": meeting_args["start_time"],
                "end_time":   meeting_args["end_time"],
            },
            retry_limit=1,
        ),
        WorkflowStep(
            name="schedule_event",
            action=schedule_fn,
            args={**meeting_args, "user_id": ctx.user_id},
            depends_on=["check_conflicts"],
            retry_limit=2,
        ),
        WorkflowStep(
            name="create_followup_task",
            action=create_task_fn,
            args={
                "user_id":     ctx.user_id,
                "title":       task_title,
                "description": f"Follow up from meeting: {meeting_args.get('title','')}",
                "priority":    "medium",
                "due_date":    "",
                "tags":        "meeting,follow-up",
            },
            depends_on=["schedule_event"],
            retry_limit=2,
        ),
    ]

    if note_content:
        steps.append(
            WorkflowStep(
                name="save_agenda_note",
                action=create_note_fn,
                args={
                    "user_id": ctx.user_id,
                    "title":   f"Agenda: {meeting_args.get('title','')}",
                    "content": note_content,
                    "tags":    "meeting,agenda",
                },
                depends_on=["schedule_event"],
                retry_limit=1,
            )
        )

    return WorkflowEngine(ctx, steps)
