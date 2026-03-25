"""Calendar integration: read tools + calendar proposals + HITL (standalone subgraph)."""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.orm import Session

from app.agent.graphs.react_graph import build_react_assistant_graph
from app.agent.prompts import (
    chat_calendar_agent_prompt,
    chat_email_agent_prompt,
    chat_main_agent_prompt,
    chat_system_prompt,
)
from app.agent.tools.hitl import build_hitl_tools
from app.agent.tools.proposals_calendar import (
    CALENDAR_PROPOSAL_TYPES,
    build_calendar_proposal_tools,
)
from app.agent.tools.read_calendar import build_read_calendar_tools
from app.config import Settings


def build_calendar_tool_bundle(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    default_timezone: str,
) -> list:
    """Tools for the calendar unit (reads + proposals + shared clarification)."""
    return [
        *build_read_calendar_tools(db, user_id, settings),
        *build_calendar_proposal_tools(
            db,
            user_id,
            settings,
            default_timezone=default_timezone,
        ),
        *build_hitl_tools(),
    ]


def build_calendar_subgraph(
    *,
    llm: BaseChatModel,
    settings: Settings,
    checkpointer: BaseCheckpointSaver,
    db: Session,
    user_id: int,
    default_timezone: str,
    approval_from_email: str | None = None,
    user_email: str | None = None,
):
    """
    Standalone calendar-only assistant subgraph (same state schema, scoped proposals).

    Use for tests or future orchestration; production uses the combined main graph.
    """
    tools = build_calendar_tool_bundle(
        db, user_id, settings, default_timezone=default_timezone
    )
    return build_react_assistant_graph(
        llm=llm,
        tools=tools,
        system_prompt=chat_system_prompt(
            user_timezone=default_timezone,
            user_email=user_email,
        ),
        settings=settings,
        checkpointer=checkpointer,
        db=db,
        user_id=user_id,
        default_timezone=default_timezone,
        proposal_types_scope=CALENDAR_PROPOSAL_TYPES,
        graph_name="calendar",
        approval_from_email=approval_from_email,
        user_email=user_email,
        main_system_prompt=chat_main_agent_prompt(
            user_timezone=default_timezone,
            user_email=user_email,
        ),
        email_system_prompt=chat_email_agent_prompt(
            user_timezone=default_timezone,
            user_email=user_email,
        ),
        calendar_system_prompt=chat_calendar_agent_prompt(
            user_timezone=default_timezone,
            user_email=user_email,
        ),
    )
