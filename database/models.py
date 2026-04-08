"""
database/models.py
SQLAlchemy ORM models — mirrors schema.sql exactly.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY, Boolean, Column, DateTime, ForeignKey,
    String, Text, func
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "tasks"

    task_id     = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(String, nullable=False, index=True)
    title       = Column(Text, nullable=False)
    description = Column(Text)
    status      = Column(String, nullable=False, default="pending")
    priority    = Column(String, nullable=False, default="medium")
    due_date    = Column(DateTime)
    tags        = Column(ARRAY(String))
    metadata_   = Column("metadata", JSONB, default=dict)
    created_at  = Column(DateTime, default=datetime.utcnow)
    updated_at  = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # relationship: a task can have linked events
    events = relationship("Event", back_populates="linked_task")

    def to_dict(self) -> dict:
        return {
            "task_id":     str(self.task_id),
            "user_id":     self.user_id,
            "title":       self.title,
            "description": self.description,
            "status":      self.status,
            "priority":    self.priority,
            "due_date":    self.due_date.isoformat() if self.due_date else None,
            "tags":        self.tags or [],
            "metadata":    self.metadata_ or {},
            "created_at":  self.created_at.isoformat() if self.created_at else None,
            "updated_at":  self.updated_at.isoformat() if self.updated_at else None,
        }


class Event(Base):
    __tablename__ = "events"

    event_id       = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id        = Column(String, nullable=False, index=True)
    title          = Column(Text, nullable=False)
    description    = Column(Text)
    start_time     = Column(DateTime, nullable=False)
    end_time       = Column(DateTime, nullable=False)
    location       = Column(Text)
    attendees      = Column(ARRAY(String))
    linked_task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.task_id"), nullable=True)
    metadata_      = Column("metadata", JSONB, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    linked_task = relationship("Task", back_populates="events")

    def to_dict(self) -> dict:
        return {
            "event_id":       str(self.event_id),
            "user_id":        self.user_id,
            "title":          self.title,
            "description":    self.description,
            "start_time":     self.start_time.isoformat() if self.start_time else None,
            "end_time":       self.end_time.isoformat() if self.end_time else None,
            "location":       self.location,
            "attendees":      self.attendees or [],
            "linked_task_id": str(self.linked_task_id) if self.linked_task_id else None,
            "metadata":       self.metadata_ or {},
            "created_at":     self.created_at.isoformat() if self.created_at else None,
        }


class Note(Base):
    __tablename__ = "notes"

    note_id        = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id        = Column(String, nullable=False, index=True)
    title          = Column(Text, nullable=False)
    content        = Column(Text, nullable=False)
    tags           = Column(ARRAY(String))
    # content_vector stored natively via AlloyDB AI; we don't map it in ORM
    metadata_      = Column("metadata", JSONB, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "note_id":    str(self.note_id),
            "user_id":    self.user_id,
            "title":      self.title,
            "content":    self.content,
            "tags":       self.tags or [],
            "metadata":   self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Interaction(Base):
    __tablename__ = "interactions"

    interaction_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id     = Column(String, nullable=False, index=True)
    user_id        = Column(String, nullable=False, index=True)
    agent_name     = Column(String, nullable=False)
    role           = Column(String, nullable=False)
    content        = Column(Text, nullable=False)
    tool_calls     = Column(JSONB, default=list)
    metadata_      = Column("metadata", JSONB, default=dict)
    created_at     = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "interaction_id": str(self.interaction_id),
            "session_id":     self.session_id,
            "user_id":        self.user_id,
            "agent_name":     self.agent_name,
            "role":           self.role,
            "content":        self.content,
            "tool_calls":     self.tool_calls or [],
            "created_at":     self.created_at.isoformat() if self.created_at else None,
        }


class Workflow(Base):
    __tablename__ = "workflows"

    workflow_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(String, nullable=False, index=True)
    name        = Column(String, nullable=False)
    status      = Column(String, nullable=False, default="running")
    steps       = Column(JSONB, default=list)
    result      = Column(JSONB)
    error       = Column(Text)
    started_at  = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)

    def to_dict(self) -> dict:
        return {
            "workflow_id":  str(self.workflow_id),
            "user_id":      self.user_id,
            "name":         self.name,
            "status":       self.status,
            "steps":        self.steps or [],
            "result":       self.result,
            "error":        self.error,
            "started_at":   self.started_at.isoformat() if self.started_at else None,
            "finished_at":  self.finished_at.isoformat() if self.finished_at else None,
        }
