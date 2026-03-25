"""
Independent integration units (calendar, Gmail). Each exposes a tool bundle and optional
standalone subgraph for testing or future orchestration.

The production assistant merges bundles in `app.agent.graphs.builder` via `build_agent_tools`.
"""

from app.agent.tools import build_agent_tools as build_main_combined_tools

from app.agent.graphs.subgraphs.calendar import (
    build_calendar_subgraph,
    build_calendar_tool_bundle,
)
from app.agent.graphs.subgraphs.gmail import build_gmail_subgraph, build_gmail_tool_bundle

__all__ = [
    "build_calendar_subgraph",
    "build_calendar_tool_bundle",
    "build_gmail_subgraph",
    "build_gmail_tool_bundle",
    "build_main_combined_tools",
]
