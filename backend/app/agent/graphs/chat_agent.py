"""
Build the compiled calendar assistant graph for a single request (DB-bound tools).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.agent.graphs.builder import build_calendar_assistant_graph
from app.agent.graphs.checkpoint import get_checkpointer
from app.agent.utils.llm import build_chat_model
from app.config import Settings


def build_chat_agent(
    settings: Settings,
    db: Session,
    user_id: int,
    *,
    user_timezone: str,
    approval_from_email: str | None = None,
    user_email: str | None = None,
):
    """
    Compile the calendar assistant StateGraph with HITL, tool limits, and Sqlite checkpointer.

    Call once per HTTP request so tools close over the active DB session.
    """
    llm = build_chat_model(settings)
    checkpointer = get_checkpointer(settings)
    return build_calendar_assistant_graph(
        llm=llm,
        settings=settings,
        checkpointer=checkpointer,
        db=db,
        user_id=user_id,
        default_timezone=user_timezone,
        approval_from_email=approval_from_email,
        user_email=user_email,
    )
