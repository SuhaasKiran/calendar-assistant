"""
Chat: LangGraph calendar assistant with SSE and HITL resume.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.graphs.chat_agent import build_chat_agent
from app.agent.graphs.state import PROPOSAL_CLEAR
from app.agent.streaming.graph_stream import stream_graph_sse
from app.config import get_settings
from app.db.models import Conversation, Message, MessageRole, User
from app.db.session import get_db
from app.deps import get_current_user
from app.schemas.chat import ChatRequest, ConversationListItem, MessageItem

router = APIRouter(prefix="/chat", tags=["chat"])

RECURSION_LIMIT = 50


def _lc_messages_from_db_rows(rows: list[Message]) -> list:
    out: list = []
    for m in rows:
        if m.role == MessageRole.user:
            out.append(HumanMessage(content=m.content))
        else:
            out.append(AIMessage(content=m.content))
    return out


@router.get("/conversations", response_model=list[ConversationListItem])
def list_conversations(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[ConversationListItem]:
    last_message_at = (
        select(func.max(Message.created_at))
        .where(Message.conversation_id == Conversation.id)
        .scalar_subquery()
    )
    last_message_preview = (
        select(Message.content)
        .where(Message.conversation_id == Conversation.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
        .scalar_subquery()
    )
    last_activity_at = func.coalesce(last_message_at, Conversation.created_at)

    rows = db.execute(
        select(
            Conversation.id,
            Conversation.created_at,
            last_activity_at.label("last_activity_at"),
            last_message_preview.label("last_message_preview"),
        )
        .where(Conversation.user_id == user.id)
        .order_by(last_activity_at.desc())
    ).all()

    return [
        ConversationListItem(
            id=row.id,
            created_at=row.created_at,
            last_activity_at=row.last_activity_at,
            last_message_preview=row.last_message_preview,
        )
        for row in rows
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageItem])
def list_conversation_messages(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[MessageItem]:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at, Message.id)
    ).all()

    return [
        MessageItem(
            id=row.id,
            role=row.role.value,
            content=row.content,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_conversation(
    conversation_id: str,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    db.delete(conv)
    db.commit()


@router.post("")
def chat_turn(
    body: ChatRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> StreamingResponse:
    settings = get_settings()
    if not settings.secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server misconfigured",
        )

    tz = user.timezone or "America/Los_Angeles"

    if body.conversation_id:
        conv = db.get(Conversation, body.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
    else:
        conv = Conversation(id=str(uuid.uuid4()), user_id=user.id)
        db.add(conv)
        db.commit()
        db.refresh(conv)

    graph = build_chat_agent(
        settings,
        db,
        user.id,
        user_timezone=tz,
        approval_from_email=user.email,
        user_email=user.email,
        user_preferences=body.user_preferences or "",
    )
    config: dict = {
        "configurable": {"thread_id": conv.id},
        "recursion_limit": RECURSION_LIMIT,
        "metadata": {
            "user_id": str(user.id),
            "conversation_id": conv.id,
        },
        "tags": ["calendar-assistant", "chat"],
        "run_name": f"chat user={user.id} conv={conv.id[:8]}",
    }

    if body.resume:
        stream_input: dict | Command = Command(resume=body.resume_value)
    else:
        assert body.message is not None
        user_text = body.message.strip()
        db.add(
            Message(
                conversation_id=conv.id,
                role=MessageRole.user,
                content=user_text,
            )
        )
        db.commit()

        prior = db.scalars(
            select(Message)
            .where(Message.conversation_id == conv.id)
            .order_by(Message.created_at)
        ).all()

        snap = graph.get_state(config)
        has_checkpoint = bool(snap.values and snap.values.get("messages"))

        if has_checkpoint:
            # Append only the new user turn; checkpoint already holds prior messages.
            stream_input = {
                "messages": [HumanMessage(content=user_text)],
                "pending_proposals": [PROPOSAL_CLEAR],
                "tool_rounds": 0,
                "loop_stopped": False,
                "tool_fingerprints": [],
            }
        else:
            # First turn (or lost checkpoint): hydrate full history from DB.
            history = _lc_messages_from_db_rows(list(prior))
            stream_input = {
                "messages": history,
                "pending_proposals": [],
                "tool_rounds": 0,
                "loop_stopped": False,
                "tool_fingerprints": [],
            }

    interrupted = {"flag": False}

    def sse():
        yield f"data: {json.dumps({'type': 'meta', 'conversation_id': conv.id})}\n\n"
        for line in stream_graph_sse(graph, input=stream_input, config=config):
            try:
                evt = json.loads(line.strip())
                if evt.get("type") == "interrupt":
                    interrupted["flag"] = True
            except json.JSONDecodeError:
                pass
            yield f"data: {line}\n"
        if interrupted["flag"]:
            return
        snap = graph.get_state(config)
        msgs = (snap.values or {}).get("messages") or []
        text = ""
        for m in reversed(msgs):
            if isinstance(m, AIMessage) and m.content and not m.tool_calls:
                c = m.content
                text = c if isinstance(c, str) else str(c)
                break
        if text:
            db.add(
                Message(
                    conversation_id=conv.id,
                    role=MessageRole.assistant,
                    content=text,
                )
            )
            db.commit()

    return StreamingResponse(sse(), media_type="text/event-stream")
