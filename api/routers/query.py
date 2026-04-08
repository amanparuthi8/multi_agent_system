"""
api/routers/query.py
/api/v1/query — primary endpoint for natural-language agent invocation.
Invokes the orchestrator (root_agent) and streams or returns the response.
Also persists the interaction to AlloyDB for long-term memory.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database.connection import db_session
from database.models import Interaction

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Pydantic models ───────────────────────────────────────────────────────────

class QueryRequest(BaseModel):
    user_id:    str   = Field(default="default_user", description="User identifier")
    session_id: str   = Field(default="", description="Session ID for conversation continuity")
    message:    str   = Field(...,  description="Natural-language message to the AI agent system")
    metadata:   dict  = Field(default_factory=dict, description="Optional extra context")


class QueryResponse(BaseModel):
    session_id:     str
    response:       str
    agent_used:     str | None = None
    tool_calls:     list[dict] = []
    interaction_id: str | None = None
    latency_ms:     float | None = None


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/query", response_model=QueryResponse)
async def query_agent(req: QueryRequest):
    """
    Send a natural-language message to the multi-agent orchestrator.
    The orchestrator routes to the appropriate sub-agent based on intent.

    Example intents:
    - "Create a task to review Q3 report by Friday"
    - "Schedule a team standup tomorrow at 9am"
    - "What do I know about our product roadmap?"
    - "Schedule a kickoff meeting next Monday and create a follow-up task"
    """
    import time

    session_id = req.session_id or str(uuid.uuid4())
    start      = time.perf_counter()

    try:
        # ── Import ADK runner (lazy import avoids startup cost) ───────────────
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai.types import Content, Part

        from agents.orchestrator import root_agent

        session_service = InMemorySessionService()
        runner = Runner(
            agent=root_agent,
            app_name="multi_agent_system",
            session_service=session_service,
        )

        # ── Create/get ADK session ────────────────────────────────────────────
        session = await session_service.create_session(
            app_name="multi_agent_system",
            user_id=req.user_id,
            session_id=session_id,
        )

        # ── Run the agent ─────────────────────────────────────────────────────
        user_message = Content(role="user", parts=[Part(text=req.message)])
        final_response = ""
        agent_used     = None
        tool_calls     = []

        async for event in runner.run_async(
            user_id=req.user_id,
            session_id=session_id,
            new_message=user_message,
        ):
            if event.is_final_response() and event.content:
                for part in event.content.parts:
                    if part.text:
                        final_response += part.text

            # Track which agent handled this
            if hasattr(event, "author") and event.author:
                agent_used = event.author

            # Collect tool calls for transparency
            if hasattr(event, "content") and event.content:
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        tool_calls.append({
                            "tool":  part.function_call.name,
                            "input": dict(part.function_call.args or {}),
                        })

        latency_ms = (time.perf_counter() - start) * 1000

        # ── Persist interaction to AlloyDB (long-term memory) ─────────────────
        interaction_id = None
        try:
            with db_session() as db:
                # user turn
                db.add(Interaction(
                    session_id=session_id,
                    user_id=req.user_id,
                    agent_name="user",
                    role="user",
                    content=req.message,
                ))
                # assistant turn
                ai_interaction = Interaction(
                    session_id=session_id,
                    user_id=req.user_id,
                    agent_name=agent_used or "orchestrator",
                    role="assistant",
                    content=final_response,
                    tool_calls=tool_calls,
                )
                db.add(ai_interaction)
                db.flush()
                interaction_id = str(ai_interaction.interaction_id)
        except Exception as db_exc:
            logger.warning("Failed to persist interaction: %s", db_exc)

        return QueryResponse(
            session_id=session_id,
            response=final_response or "(no response generated)",
            agent_used=agent_used,
            tool_calls=tool_calls,
            interaction_id=interaction_id,
            latency_ms=round(latency_ms, 1),
        )

    except Exception as exc:
        logger.error("Query failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc))
