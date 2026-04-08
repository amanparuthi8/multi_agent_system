"""
agents/calendar_agent.py
Specialised sub-agent: manages calendar events and scheduling.
Always checks for conflicts before confirming a booking.
"""
from __future__ import annotations

import logging

from google.adk.agents import Agent

from tools.mcp_tools import load_calendar_tools

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"


def build_calendar_agent() -> Agent:
    tools = load_calendar_tools()
    logger.info("CalendarAgent loaded %d MCP tools", len(tools))

    return Agent(
        name="calendar_agent",
        model=MODEL,
        description=(
            "Specialised agent for scheduling and calendar management. "
            "Schedules meetings, lists upcoming events, and detects time conflicts. "
            "Can link events to existing tasks."
        ),
        instruction="""
You are the Calendar Manager agent. Your responsibilities:

  1. SCHEDULE EVENTS when the user asks to book, schedule, or set a meeting.
     Workflow (MANDATORY ORDER):
       a. Call check_conflicts with proposed start_time and end_time.
       b. If conflict_count > 0: report the conflicting events and ask
          the user to choose a different time. Do NOT schedule.
       c. If no conflict: call schedule_event and confirm with:
          "📅 Event '<title>' scheduled for <start_time> → <end_time>."
     Parameters to extract: title, description, start_time (ISO-8601),
     end_time (ISO-8601), location, attendees (comma-separated emails),
     linked_task_id (only if the user explicitly mentions a task).

  2. LIST EVENTS when the user asks what's coming up.
     - Parse natural date expressions ("this week", "tomorrow", "next Monday")
       into ISO-8601 datetimes.
     - Format: chronological list with 📅 emoji, time, and location.

  3. DETECT CONFLICTS on demand or before scheduling.

Rules:
  - ALWAYS run conflict check before creating any event.
  - If linked_task_id is provided, validate it looks like a UUID.
  - Use sensible defaults: if no end_time given, assume 1-hour duration.
  - Express times in the user's apparent timezone; default UTC.
""",
        tools=tools,
        output_key="calendar_agent_result",
    )
