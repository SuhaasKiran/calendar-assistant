"""
Main assistant graph: merges calendar + Gmail tool bundles into one ReAct graph.

Standalone unit subgraphs live in `app.agent.graphs.subgraphs` (calendar-only, gmail-only).
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.orm import Session

from app.agent.graphs.react_graph import build_react_assistant_graph
from app.agent.prompts import chat_system_prompt
from app.agent.tools import build_agent_tools
from app.config import Settings


def build_calendar_assistant_graph(
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
    Production graph: calendar reads + calendar/Gmail proposals + HITL in one loop.

    `db` / `user_id` are captured for the execute_mutations node (same session as request).
    """
    tools = build_agent_tools(
        db,
        user_id,
        settings,
        default_timezone=default_timezone,
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
        proposal_types_scope=None,
        graph_name="main",
        approval_from_email=approval_from_email,
        user_email=user_email,
    )
