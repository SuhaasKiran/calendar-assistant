"""
LangChain tool definitions for Calendar and Gmail.

Read tools call Google APIs immediately. Proposal tools queue mutations until approval.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.tools.hitl import build_hitl_tools
from app.agent.tools.proposals import build_proposal_tools
from app.agent.tools.read_calendar import build_read_calendar_tools
from app.config import Settings


def build_agent_tools(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    default_timezone: str,
) -> list:
    """
    All tools for the calendar assistant: reads, proposals (gated writes), and HITL.

    `default_timezone` is used when executing approved updates (fallback for tz).
    """
    _ = default_timezone  # reserved for future context injection; execution uses closure
    return [
        *build_read_calendar_tools(db, user_id, settings),
        *build_proposal_tools(db, user_id, settings),
        *build_hitl_tools(),
    ]


__all__ = [
    "build_agent_tools",
    "build_hitl_tools",
    "build_proposal_tools",
    "build_read_calendar_tools",
]
