"""
agents/knowledge_agent.py
Specialised sub-agent: manages the semantic notes / knowledge base.
Uses AlloyDB AI (pgvector + text-embedding-005) for similarity search.
"""
from __future__ import annotations

import logging

from google.adk.agents import Agent

from tools.mcp_tools import load_knowledge_tools, load_memory_tools

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"


def build_knowledge_agent() -> Agent:
    tools = load_knowledge_tools() + load_memory_tools()
    logger.info("KnowledgeAgent loaded %d MCP tools", len(tools))

    return Agent(
        name="knowledge_agent",
        model=MODEL,
        description=(
            "Specialised agent for managing notes and semantic knowledge retrieval. "
            "Saves notes with AI-generated embeddings and performs natural-language "
            "search over stored knowledge. Also retrieves session memory context."
        ),
        instruction="""
You are the Knowledge Manager agent. Your responsibilities:

  1. SAVE NOTES when the user wants to remember, document, or store information.
     - Extract: title (infer if not given), content, tags.
     - Call create_note (AlloyDB AI auto-embeds during INSERT).
     - Confirm: "📝 Note '<title>' saved."

  2. SEARCH the knowledge base when the user asks:
     - "Do I have notes about X?"
     - "What do I know about Y?"
     - "Find my notes related to Z."
     - Call search_notes with user's query and top_k=5.
     - Rank results by similarity score and present concisely.
     - If similarity < 0.4 on best result, say "I didn't find close matches."

  3. RECALL SESSION CONTEXT via get_recent_interactions when:
     - The user says "as I mentioned earlier" or references past exchanges.
     - Another agent needs prior conversation context.
     - Return the last 10 interactions for the current session.

Rules:
  - Embeddings are generated inside AlloyDB — never call an embedding API yourself.
  - Always show similarity scores (rounded to 2 decimal places) in search results.
  - Keep note summaries under 200 chars in responses; offer to show full content.
""",
        tools=tools,
        output_key="knowledge_agent_result",
    )
