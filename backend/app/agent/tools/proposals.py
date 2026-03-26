"""Proposal tools: re-export calendar + Gmail builders for backward compatibility."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.tools.proposals_calendar import (
    CALENDAR_PROPOSAL_TYPES,
    build_calendar_proposal_tools,
)
from app.agent.tools.proposals_gmail import GMAIL_PROPOSAL_TYPES, build_gmail_proposal_tools
from app.config import Settings


def build_proposal_tools(
    db: Session,
    user_id: int,
    settings: Settings,
) -> list:
    """All proposal tools (calendar + Gmail)."""
    return [
        *build_calendar_proposal_tools(db, user_id, settings),
        *build_gmail_proposal_tools(db, user_id, settings),
    ]


__all__ = [
    "CALENDAR_PROPOSAL_TYPES",
    "GMAIL_PROPOSAL_TYPES",
    "build_calendar_proposal_tools",
    "build_gmail_proposal_tools",
    "build_proposal_tools",
]
