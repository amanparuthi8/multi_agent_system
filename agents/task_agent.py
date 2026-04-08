"""
agents/task_agent.py
Specialized sub-agent: owns all task CRUD operations.
Tools are loaded exclusively from the task_toolset via MCP Toolbox.
"""
from __future__ import annotations

import logging

from google.adk.agents import Agent

from tools.mcp_tools import load_task_tools

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"


def build_task_agent() -> Agent:
    """
    Factory — build and return a fresh TaskAgent with live MCP tools.
    Called once at startup so tool references are stable.
    """
    tools = load_task_tools()
    logger.info("TaskAgent loaded %d MCP tools", len(tools))

    return Agent(
        name="task_agent",
        model=MODEL,
        description=(
            "Specialised agent for managing user tasks. "
            "Can create, list, update status, and delete tasks. "
            "Always confirms the action taken with a concise summary."
        ),
        instruction="""
You are the Task Manager agent. Your responsibilities:
  1. CREATE tasks when the user describes something to do.
     - Extract: title, description, priority (default=medium), due_date, tags.
     - Infer priority from urgency language ("ASAP" → critical, "soon" → high).
     - Call create_task and confirm with "✅ Task '<title>' created (ID: <task_id>)."
  2. LIST tasks when the user asks what they need to do.
     - Apply status filter if they say "pending", "done", etc.
     - Format results as a numbered list with priority emoji:
       🔴 critical  🟠 high  🟡 medium  🟢 low
  3. UPDATE task status when the user marks progress.
     - Recognise phrases: "done", "finished", "cancel", "start working on".
     - Map to status: done / cancelled / in_progress.
  4. DELETE tasks only when explicitly asked.

Rules:
  - Always include the task_id in confirmations so other agents can reference it.
  - If you cannot determine the user_id, use the session's user_id from context.
  - Never fabricate task data — call the tools.
""",
        tools=tools,
        output_key="task_agent_result",
    )
