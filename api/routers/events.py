"""
api/routers/events.py
REST endpoints for calendar event operations.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database.connection import db_session
from database.models import Event

router = APIRouter()


class EventCreate(BaseModel):
    user_id:        str
    title:          str
    description:    Optional[str] = None
    start_time:     str                       # ISO-8601
    end_time:       str                       # ISO-8601
    location:       Optional[str]  = None
    attendees:      list[str]      = []
    linked_task_id: Optional[str]  = None


@router.post("/", status_code=201)
def create_event(body: EventCreate):
    with db_session() as db:
        event = Event(
            user_id=body.user_id,
            title=body.title,
            description=body.description,
            start_time=datetime.fromisoformat(body.start_time),
            end_time=datetime.fromisoformat(body.end_time),
            location=body.location,
            attendees=body.attendees,
            linked_task_id=uuid.UUID(body.linked_task_id) if body.linked_task_id else None,
        )
        db.add(event)
        db.flush()
        return event.to_dict()


@router.get("/")
def list_events(
    user_id:   str,
    from_time: Optional[str] = None,
    to_time:   Optional[str] = None,
    limit:     int           = Query(50, le=200),
):
    with db_session() as db:
        q = db.query(Event).filter(Event.user_id == user_id)
        if from_time:
            q = q.filter(Event.start_time >= datetime.fromisoformat(from_time))
        if to_time:
            q = q.filter(Event.start_time <= datetime.fromisoformat(to_time))
        events = q.order_by(Event.start_time.asc()).limit(limit).all()
        return {"items": [e.to_dict() for e in events]}


@router.get("/{event_id}")
def get_event(event_id: str):
    with db_session() as db:
        event = db.query(Event).filter(Event.event_id == uuid.UUID(event_id)).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        return event.to_dict()


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: str):
    with db_session() as db:
        event = db.query(Event).filter(Event.event_id == uuid.UUID(event_id)).first()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        db.delete(event)
