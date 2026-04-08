"""
agents/orchestrator.py
Primary Orchestrator Agent — the root_agent exposed to users.
Pattern: Lab 1 SequentialAgent + greeter pattern, extended with
LlmAgent routing to specialised sub-agents (Lab 3 multi-MCP pattern).

Routing logic:
  user query → intent classification → delegate to sub-agent
  ┌─────────────────────────────────────────────────┐
  │              root_agent (orchestrator)          │
  │  1. Saves user_id + session_id to shared state  │
  │  2. Classifies intent                           │
  │  3. Transfers to correct sub-agent              │
  └────────┬────────────┬────────────┬──────────────┘
           │            │            │            │
     task_agent  calendar_agent  knowledge_  workflow_
                               agent        agent
"""
from __future__ import annotations

import logging
import os

from google.adk.agents import Agent, SequentialAgent
from google.adk.tools.tool_context import ToolContext

from agents.task_agent      import build_task_agent
from agents.calendar_agent  import build_calendar_agent
from agents.knowledge_agent import build_knowledge_agent
from agents.workflow_agent  import build_workflow_agent
from tools.mcp_tools        import load_memory_tools

logger = logging.getLogger(__name__)

MODEL = os.getenv("MODEL", "gemini-2.5-flash")


# ── State-initialisation tool ─────────────────────────────────────────────────

def init_session_state(
    tool_context: ToolContext,
    user_id: str,
    session_id: str,
    raw_query: str,
) -> dict:
    """
    Saves user_id, session_id, and the raw query to ADK shared state.
    Called by the orchestrator at the start of every turn so sub-agents
    can access the user context without re-parsing it.
    """
    tool_context.state["user_id"]   = user_id
    tool_context.state["session_id"] = session_id
    tool_context.state["raw_query"] = raw_query
    logger.info("Session state initialised: user=%s session=%s", user_id, session_id)
    return {"status": "ok", "user_id": user_id, "session_id": session_id}


# ── Build all sub-agents ──────────────────────────────────────────────────────

def build_root_agent() -> Agent:
    """
    Factory — assembles the full multi-agent tree.
    Returns the root_agent ready to be served by ADK.
    """
    task_agent      = build_task_agent()
    calendar_agent  = build_calendar_agent()
    knowledge_agent = build_knowledge_agent()
    workflow_agent  = build_workflow_agent()
    memory_tools    = load_memory_tools()

    root_agent = Agent(
        name="orchestrator",
        model=MODEL,
        description="Primary AI assistant that manages tasks, schedules, and knowledge.",
        instruction=f"""
You are the central Orchestrator for a personal AI assistant system.
Your role is coordination and intent routing — you do NOT directly
manipulate data yourself.

=== SESSION INITIALISATION (every turn) ===
At the start of each user message, call init_session_state with:
  - user_id:   extract from context, or use "default_user" if unknown
  - session_id: a unique identifier for this conversation
  - raw_query: the user's verbatim message

=== INTENT ROUTING RULES ===
After init, classify the user's intent and transfer to the right agent:

  TASK operations → transfer to "task_agent"
    Keywords: create task, add todo, remind me, mark done, finish,
              what's on my list, pending tasks, cancel task

  CALENDAR operations → transfer to "calendar_agent"
    Keywords: schedule, book, meeting, appointment, event, when is,
              what's on my calendar, free time, available

  KNOWLEDGE operations → transfer to "knowledge_agent"
    Keywords: note, remember, save, what do I know about, find notes,
              search my knowledge, recall, look up

  COMPOUND / MULTI-STEP → transfer to "workflow_agent"
    Keywords: "schedule X and create", "plan my week", "set up",
              multiple actions in one sentence, any request spanning
              2+ domains (task + calendar, event + note, etc.)

=== AMBIGUOUS QUERIES ===
  - If intent is unclear, ask one clarifying question.
  - If the user greets you (hi, hello), respond warmly and briefly
    describe your capabilities. Do NOT transfer to a sub-agent.
  - If the user asks about their history, use get_recent_interactions.

=== RESPONSE FORMAT ===
  - Be concise and actionable.
  - Always confirm what was done in plain language after the sub-agent responds.
  - Surface errors clearly: "⚠️ <agent> encountered an issue: <error>. Retrying..."
  - At the end of complex workflows, add a one-line summary: "✅ Done: <what happened>"

Model in use: {MODEL}
""",
        tools=[init_session_state] + memory_tools,
        sub_agents=[task_agent, calendar_agent, knowledge_agent, workflow_agent],
    )

    logger.info(
        "Orchestrator built with sub-agents: %s",
        [a.name for a in [task_agent, calendar_agent, knowledge_agent, workflow_agent]],
    )
    return root_agent


# ── Module-level singleton (ADK expects `root_agent` in the package) ──────────
root_agent = build_root_agent()
