"""Gmail integration: proposal tools only + HITL (standalone subgraph)."""

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
from app.agent.tools.proposals_gmail import GMAIL_PROPOSAL_TYPES, build_gmail_proposal_tools
from app.config import Settings


def build_gmail_tool_bundle() -> list:
    """Tools for the Gmail unit (proposals + shared clarification)."""
    return [*build_gmail_proposal_tools(), *build_hitl_tools()]


def build_gmail_subgraph(
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
    Standalone Gmail-only assistant subgraph (same state schema, scoped proposals).

    Calendar reads are not available here; use the combined main graph for full UX.
    """
    tools = build_gmail_tool_bundle()
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
        proposal_types_scope=GMAIL_PROPOSAL_TYPES,
        graph_name="gmail",
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
