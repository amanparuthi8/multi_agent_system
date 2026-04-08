"""
tools/mcp_tools.py
Loads ADK-compatible toolsets from the running MCP Toolbox server.
Pattern from Lab 4 (toolbox-core ToolboxSyncClient) and Lab 3
(MCPToolset + StreamableHTTPConnectionParams for remote MCP).
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from toolbox_core import ToolboxSyncClient

logger = logging.getLogger(__name__)

TOOLBOX_URL = os.getenv("MCP_TOOLBOX_URL", "http://127.0.0.1:5000")


@lru_cache(maxsize=None)
def _get_client() -> ToolboxSyncClient:
    """Singleton MCP Toolbox client — reused across all agent instances."""
    client = ToolboxSyncClient(TOOLBOX_URL)
    logger.info("MCP Toolbox client connected at %s", TOOLBOX_URL)
    return client


def load_task_tools() -> list[Any]:
    """Load the task_toolset from MCP Toolbox."""
    return _get_client().load_toolset("task_toolset")


def load_calendar_tools() -> list[Any]:
    """Load the calendar_toolset from MCP Toolbox."""
    return _get_client().load_toolset("calendar_toolset")


def load_knowledge_tools() -> list[Any]:
    """Load the knowledge_toolset (notes + semantic search)."""
    return _get_client().load_toolset("knowledge_toolset")


def load_memory_tools() -> list[Any]:
    """Load interaction history tools for context recall."""
    return _get_client().load_toolset("memory_toolset")


def load_all_tools() -> list[Any]:
    """Load the full_toolset — used by the orchestrator for planning."""
    return _get_client().load_toolset("full_toolset")


def health_check() -> bool:
    """Ping MCP Toolbox to verify it's reachable before starting agents."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{TOOLBOX_URL}/api/toolset", timeout=5) as r:
            return r.status == 200
    except Exception as exc:
        logger.error("MCP Toolbox health check failed: %s", exc)
        return False
