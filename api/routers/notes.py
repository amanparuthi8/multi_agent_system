"""
api/routers/notes.py
REST endpoints for notes / knowledge base operations.
Semantic search is delegated to the knowledge_agent via the query endpoint,
but direct vector search is also available here for programmatic access.
"""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text

from database.connection import db_session, get_engine
from database.models import Note

router = APIRouter()


class NoteCreate(BaseModel):
    user_id: str
    title:   str
    content: str
    tags:    list[str] = []


class NoteSearchRequest(BaseModel):
    user_id: str
    query:   str
    top_k:   int = 5


@router.post("/", status_code=201)
def create_note(body: NoteCreate):
    """
    Create a note. The AlloyDB AI embedding is generated via the MCP
    create_note tool (which embeds during INSERT). This direct endpoint
    inserts without an embedding — use the agent /query endpoint for
    embedding-backed creation.
    """
    with db_session() as db:
        note = Note(
            user_id=body.user_id,
            title=body.title,
            content=body.content,
            tags=body.tags,
        )
        db.add(note)
        db.flush()
        return note.to_dict()


@router.get("/")
def list_notes(
    user_id: str,
    tag:     Optional[str] = None,
    limit:   int           = Query(50, le=200),
):
    with db_session() as db:
        q = db.query(Note).filter(Note.user_id == user_id)
        if tag:
            q = q.filter(Note.tags.contains([tag]))
        notes = q.order_by(Note.created_at.desc()).limit(limit).all()
        return {"items": [n.to_dict() for n in notes]}


@router.get("/{note_id}")
def get_note(note_id: str):
    with db_session() as db:
        note = db.query(Note).filter(Note.note_id == uuid.UUID(note_id)).first()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        return note.to_dict()


@router.post("/search")
def search_notes(body: NoteSearchRequest):
    """
    Semantic similarity search using AlloyDB AI pgvector.
    Requires the content_vector column to be populated (via MCP create_note tool).
    """
    sql = text("""
        SELECT note_id, title, content, tags,
               1 - (content_vector <=> embedding('text-embedding-005', :query)::vector)
               AS similarity
        FROM notes
        WHERE user_id = :user_id
          AND content_vector IS NOT NULL
        ORDER BY content_vector <=> embedding('text-embedding-005', :query)::vector
        LIMIT :top_k
    """)
    with get_engine().connect() as conn:
        rows = conn.execute(sql, {"user_id": body.user_id, "query": body.query, "top_k": body.top_k})
        results = [
            {
                "note_id":    str(row.note_id),
                "title":      row.title,
                "content":    row.content[:300] + ("..." if len(row.content) > 300 else ""),
                "tags":       row.tags or [],
                "similarity": round(float(row.similarity), 4),
            }
            for row in rows
        ]
    return {"query": body.query, "results": results}


@router.delete("/{note_id}", status_code=204)
def delete_note(note_id: str):
    with db_session() as db:
        note = db.query(Note).filter(Note.note_id == uuid.UUID(note_id)).first()
        if not note:
            raise HTTPException(status_code=404, detail="Note not found")
        db.delete(note)
