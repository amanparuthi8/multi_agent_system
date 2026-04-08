"""
api/routers/tasks.py
REST endpoints for direct task operations (bypass agent for programmatic use).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import asc, desc

from database.connection import db_session
from database.models import Task

router = APIRouter()


class TaskCreate(BaseModel):
    user_id:     str
    title:       str
    description: Optional[str] = None
    priority:    str            = "medium"
    due_date:    Optional[str]  = None   # ISO-8601 string
    tags:        list[str]      = []


class TaskUpdate(BaseModel):
    title:       Optional[str] = None
    description: Optional[str] = None
    status:      Optional[str] = None
    priority:    Optional[str] = None
    due_date:    Optional[str] = None
    tags:        Optional[list[str]] = None


@router.post("/", status_code=201)
def create_task(body: TaskCreate):
    with db_session() as db:
        task = Task(
            user_id=body.user_id,
            title=body.title,
            description=body.description,
            priority=body.priority,
            due_date=datetime.fromisoformat(body.due_date) if body.due_date else None,
            tags=body.tags or [],
        )
        db.add(task)
        db.flush()
        return task.to_dict()


@router.get("/")
def list_tasks(
    user_id:       str,
    status_filter: Optional[str]  = Query(None, alias="status"),
    priority:      Optional[str]  = None,
    limit:         int            = Query(50, le=200),
    offset:        int            = 0,
):
    with db_session() as db:
        q = db.query(Task).filter(Task.user_id == user_id)
        if status_filter:
            q = q.filter(Task.status == status_filter)
        if priority:
            q = q.filter(Task.priority == priority)
        total  = q.count()
        tasks  = q.order_by(Task.created_at.desc()).offset(offset).limit(limit).all()
        return {
            "total": total,
            "items": [t.to_dict() for t in tasks],
        }


@router.get("/{task_id}")
def get_task(task_id: str):
    with db_session() as db:
        task = db.query(Task).filter(Task.task_id == uuid.UUID(task_id)).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task.to_dict()


@router.patch("/{task_id}")
def update_task(task_id: str, body: TaskUpdate):
    with db_session() as db:
        task = db.query(Task).filter(Task.task_id == uuid.UUID(task_id)).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        if body.title       is not None: task.title       = body.title
        if body.description is not None: task.description = body.description
        if body.status      is not None: task.status      = body.status
        if body.priority    is not None: task.priority    = body.priority
        if body.tags        is not None: task.tags        = body.tags
        if body.due_date    is not None:
            task.due_date = datetime.fromisoformat(body.due_date)
        task.updated_at = datetime.utcnow()
        db.flush()
        return task.to_dict()


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: str):
    with db_session() as db:
        task = db.query(Task).filter(Task.task_id == uuid.UUID(task_id)).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        db.delete(task)
