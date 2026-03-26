"""
Shared ReAct loop: agent, tools, HITL interrupts, execute, graceful stop.

Used by the main assistant graph and by standalone unit subgraphs (calendar-only, gmail-only).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.types import interrupt
from sqlalchemy.orm import Session

from app.agent.graphs.routing import (
    check_tool_loop_limits,
    fingerprint_tool_calls,
    route_after_approval,
    route_after_tools,
)
from app.agent.graphs.state import (
    PROPOSAL_CLEAR,
    SUMMARY_KEEP_RECENT_MESSAGES,
    SUMMARY_TRIGGER_MESSAGES,
    CalendarAgentState,
)
from app.agent.prompts import chat_context_prompt
from app.agent.tools.execution import execute_all_proposals, format_execution_summary
from app.config import Settings

logger = logging.getLogger(__name__)


def _current_time_context(tz_name: str) -> tuple[str, str, str]:
    """Return local date/day context in user timezone."""
    try:
        z = ZoneInfo(tz_name)
        resolved_tz = tz_name
    except Exception:
        z = ZoneInfo("UTC")
        resolved_tz = "UTC"
    now = datetime.now(z)
    return (
        resolved_tz,
        now.strftime("%Y-%m-%d"),
        now.strftime("%A"),
    )


def _tool_call_ids_from_ai(ai: AIMessage) -> set[str]:
    """Collect OpenAI/LangChain tool call ids from an assistant message."""
    ids: set[str] = set()
    for tc in ai.tool_calls or []:
        if isinstance(tc, dict):
            tid = tc.get("id") or tc.get("tool_call_id")
        else:
            tid = getattr(tc, "id", None) or getattr(tc, "tool_call_id", None)
        if tid:
            ids.add(str(tid))
    return ids


def _repair_openai_tool_message_chain(messages: list[Any]) -> list[Any]:
    """
    Ensure every ``AIMessage`` with ``tool_calls`` is followed by a ``ToolMessage``
    for each ``tool_call_id``. OpenAI rejects requests otherwise (400).

    Inserts placeholder tool messages when checkpoint + new user turns leave an
    assistant tool-calling message without matching tool results.
    """
    out: list[Any] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if isinstance(m, ToolMessage):
            logger.warning(
                "react_graph dropping orphan ToolMessage tool_call_id=%s",
                getattr(m, "tool_call_id", None),
            )
            i += 1
            continue
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            needed = _tool_call_ids_from_ai(m)
            out.append(m)
            i += 1
            seen: set[str] = set()
            while i < len(messages) and isinstance(messages[i], ToolMessage):
                tm = messages[i]
                tid = getattr(tm, "tool_call_id", None) or ""
                if tid:
                    seen.add(str(tid))
                out.append(tm)
                i += 1
            missing = needed - seen
            if missing:
                logger.warning(
                    "react_graph inserting synthetic ToolMessages for missing "
                    "tool_call_ids=%s",
                    sorted(missing),
                )
                for mid in sorted(missing):
                    out.append(
                        ToolMessage(
                            content=(
                                "Tool call did not complete or session state was "
                                "inconsistent; retry if needed."
                            ),
                            tool_call_id=mid,
                            name="tool_recovery",
                        )
                    )
            continue
        out.append(m)
        i += 1
    return out


def _tool_names_for_log(tools: list) -> list[str]:
    """Stable list of tool names bound to the LLM (for debugging missing calendar tools)."""
    names: list[str] = []
    for t in tools:
        n = getattr(t, "name", None)
        if callable(n):
            try:
                n = n()  # type: ignore[misc]
            except Exception:
                n = None
        if n is None and hasattr(t, "get_name"):
            try:
                n = t.get_name()  # type: ignore[union-attr]
            except Exception:
                n = None
        if isinstance(n, str) and n:
            names.append(n)
    return names


def _fmt_optional(text: str | None) -> str:
    s = (text or "").strip()
    return s if s else "—"


def _fmt_participants(p: dict[str, Any]) -> str:
    raw = p.get("attendees")
    if raw is None or raw == "":
        return "—"
    if isinstance(raw, list):
        return "\n".join(str(x).strip() for x in raw if str(x).strip()) or "—"
    return str(raw).strip()


def _fmt_event_link(p: dict[str, Any]) -> str:
    raw = p.get("event_link")
    if not isinstance(raw, str):
        return "—"
    link = raw.strip()
    if not link:
        return "—"
    return f"[Open calendar event]({link})"


def _message_role_label(msg: Any) -> str:
    if isinstance(msg, HumanMessage):
        return "User"
    if isinstance(msg, ToolMessage):
        return "Tool"
    if isinstance(msg, AIMessage):
        return "Assistant"
    role = getattr(msg, "type", None)
    return str(role).title() if isinstance(role, str) and role else "Message"


def _message_content_text(msg: Any) -> str:
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                txt = block.get("text")
                if txt is not None:
                    parts.append(str(txt))
        return "".join(parts).strip()
    return str(content).strip()


def _safe_json_text(text: str) -> str:
    """Normalize text so downstream JSON payload encoding cannot fail on bad codepoints."""
    if not text:
        return text
    cleaned = text.replace("\x00", "")
    return cleaned.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def _sanitize_message_for_llm(msg: Any) -> Any:
    """Return a message with JSON-safe textual content."""
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        safe = _safe_json_text(content)
        if safe != content and hasattr(msg, "model_copy"):
            return msg.model_copy(update={"content": safe})
        return msg
    if isinstance(content, list):
        changed = False
        safe_blocks: list[Any] = []
        for block in content:
            if isinstance(block, str):
                safe_block = _safe_json_text(block)
                changed = changed or (safe_block != block)
                safe_blocks.append(safe_block)
            elif isinstance(block, dict):
                b = dict(block)
                txt = b.get("text")
                if isinstance(txt, str):
                    safe_txt = _safe_json_text(txt)
                    if safe_txt != txt:
                        b["text"] = safe_txt
                        changed = True
                safe_blocks.append(b)
            else:
                safe_blocks.append(block)
        if changed and hasattr(msg, "model_copy"):
            return msg.model_copy(update={"content": safe_blocks})
        return msg
    return msg


def _render_recent_messages(messages: list[Any]) -> str:
    lines: list[str] = []
    for msg in messages:
        if getattr(msg, "type", None) == "system":
            continue
        text = _message_content_text(msg)
        if not text:
            continue
        clipped = text if len(text) <= 800 else f"{text[:800]}..."
        lines.append(f"{_message_role_label(msg)}: {clipped}")
    return "\n".join(lines).strip()


def _summarize_chunk(
    *,
    llm: BaseChatModel,
    prior_summary: str | None,
    chunk_text: str,
) -> str | None:
    if not chunk_text.strip():
        return prior_summary
    summarizer_prompt = (
        "You maintain a compact rolling summary of a chat conversation. "
        "Merge the existing summary with the new transcript chunk. "
        "Preserve user preferences, constraints, unresolved asks, proposed actions, "
        "and important outcomes. Keep it concise, factual, and under 180 words."
    )
    existing = prior_summary.strip() if prior_summary else "None."
    msg = llm.invoke(
        [
            SystemMessage(content=summarizer_prompt),
            HumanMessage(
                content=(
                    f"Existing summary:\n{existing}\n\n"
                    f"New transcript chunk:\n{chunk_text}\n\n"
                    "Return only the updated summary."
                )
            ),
        ]
    )
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        out = content.strip()
    else:
        out = str(content).strip()
    return out or prior_summary


def _format_calendar_create_block(p: dict[str, Any]) -> str:
    tz = p.get("timezone") or ""
    start = p.get("start_datetime") or "—"
    end = p.get("end_datetime") or "—"
    start_line = f"{start}" + (f" ({tz})" if tz and tz not in str(start) else "")
    end_line = f"{end}" + (f" ({tz})" if tz and tz not in str(end) else "")
    title = p.get("summary") or "—"
    desc = p.get("description")
    return (
        "Calendar — Create event\n\n"
        "Title\n"
        f"{title}\n\n"
        "Summary\n"
        f"{_fmt_optional(desc)}\n\n"
        "Start Time\n"
        f"{start_line}\n\n"
        "End Time\n"
        f"{end_line}\n\n"
        "Participants\n"
        f"{_fmt_participants(p)}\n\n"
        "Event\n"
        f"{_fmt_event_link(p)}"
    )


def _format_calendar_update_block(p: dict[str, Any]) -> str:
    tz = p.get("timezone") or ""
    st = p.get("start_datetime") or "—"
    en = p.get("end_datetime") or "—"
    start_line = f"{st}" + (f" ({tz})" if tz and st != "—" else "")
    end_line = f"{en}" + (f" ({tz})" if tz and en != "—" else "")
    title = p.get("summary") if p.get("summary") is not None else "—"
    desc = p.get("description") if p.get("description") is not None else None
    return (
        "Calendar — Update event\n\n"
        "Title\n"
        f"{title or '—'}\n\n"
        "Summary (Optional)\n"
        f"{_fmt_optional(desc)}\n\n"
        "Start Time\n"
        f"{start_line}\n\n"
        "End Time\n"
        f"{end_line}\n\n"
        "Participants\n"
        f"{_fmt_participants(p)}\n\n"
        "Event\n"
        f"{_fmt_event_link(p)}"
    )


def _format_calendar_delete_block(p: dict[str, Any]) -> str:
    tz = p.get("timezone") or ""
    st = p.get("start_datetime") or "—"
    en = p.get("end_datetime") or "—"
    start_line = f"{st}" + (f" ({tz})" if tz and st != "—" else "")
    end_line = f"{en}" + (f" ({tz})" if tz and en != "—" else "")
    title = p.get("summary") if p.get("summary") is not None else "—"
    desc = p.get("description") if p.get("description") is not None else None
    return (
        "Calendar — Delete event\n\n"
        "Title\n"
        f"{title or '—'}\n\n"
        "Summary (Optional)\n"
        f"{_fmt_optional(desc)}\n\n"
        "Start Time\n"
        f"{start_line}\n\n"
        "End Time\n"
        f"{end_line}\n\n"
        "Participants\n"
        f"{_fmt_participants(p)}\n\n"
        "Event\n"
        f"{_fmt_event_link(p)}"
    )


def _format_email_block(p: dict[str, Any], *, from_email: str | None) -> str:
    action = "Create draft" if p.get("type") == "create_email_draft" else "Send email"
    from_line = from_email.strip() if (from_email and from_email.strip()) else "—"
    return (
        f"Email — {action}\n\n"
        "From:\n"
        f"{from_line}\n\n"
        "To:\n"
        f"{p.get('to') or '—'}\n\n"
        "Subject:\n"
        f"{p.get('subject') or '—'}\n\n"
        "Draft:\n"
        f"{p.get('body') or '—'}"
    )


def _format_approval_display(
    proposals: list[dict[str, Any]],
    *,
    from_email: str | None,
) -> str:
    """Human-readable confirmation text (not JSON) for the approval interrupt UI."""
    blocks: list[str] = []
    for p in proposals:
        if p.get("type") == "__clear__":
            continue
        t = p.get("type")
        if t == "create_event":
            blocks.append(_format_calendar_create_block(p))
        elif t == "update_event":
            blocks.append(_format_calendar_update_block(p))
        elif t == "delete_event":
            blocks.append(_format_calendar_delete_block(p))
        elif t in ("create_email_draft", "send_email"):
            blocks.append(_format_email_block(p, from_email=from_email))
        else:
            blocks.append(f"(Unknown proposal type: {t!r})")
    return "\n\n---\n\n".join(blocks) if blocks else "(no proposals)"


def _parse_approval_resume(resp: Any) -> Literal["approve", "reject", "edit"]:
    if isinstance(resp, bool):
        return "approve" if resp else "reject"
    if isinstance(resp, dict):
        action = str(resp.get("action", "")).strip().lower()
        if action in {"approve", "approved", "reject", "rejected", "edit"}:
            if action in {"approve", "approved"}:
                return "approve"
            if action in {"reject", "rejected"}:
                return "reject"
            return "edit"
        if bool(resp.get("edit")):
            return "edit"
        if bool(resp.get("approved") or resp.get("approve")):
            return "approve"
        return "reject"
    if isinstance(resp, str):
        low = resp.strip().lower()
        if low in ("edit", "revise", "change", "modify"):
            return "edit"
        if low in ("yes", "y", "approve", "approved", "true", "1"):
            return "approve"
    return "reject"


def _approval_edit_feedback(resp: Any) -> str | None:
    if isinstance(resp, dict):
        raw = resp.get("feedback")
        if raw is None:
            return None
        text = str(raw).strip()
        return text or None
    return None


def _filter_proposals_by_scope(
    proposals: list[dict[str, Any]],
    scope: frozenset[str] | None,
) -> list[dict[str, Any]]:
    out = [p for p in proposals if p.get("type") not in (None, "__clear__")]
    if scope is None:
        return out
    return [p for p in out if p.get("type") in scope]


def route_from_agent_scoped(
    state: CalendarAgentState,
    *,
    proposal_types_scope: frozenset[str] | None,
) -> Literal["tools", "approval_gate", "__end__"]:
    if tools_condition(state) == "tools":
        return "tools"
    props = _filter_proposals_by_scope(
        list(state.get("pending_proposals") or []),
        proposal_types_scope,
    )
    if props:
        return "approval_gate"
    return "__end__"


def build_react_assistant_graph(
    *,
    llm: BaseChatModel,
    tools: list,
    system_prompt: str,
    settings: Settings,
    checkpointer: BaseCheckpointSaver,
    db: Session,
    user_id: int,
    default_timezone: str,
    proposal_types_scope: frozenset[str] | None = None,
    graph_name: str = "assistant",
    approval_from_email: str | None = None,
    user_email: str | None = None,
):
    """
    Compile a ReAct-style graph with optional proposal scope.

    If ``proposal_types_scope`` is set (standalone unit subgraph), approval and execution
    only consider proposals whose ``type`` is in the set. The main combined graph passes
    ``None`` to handle calendar + Gmail proposals together.
    """
    tool_node = ToolNode(tools)
    bound_tool_names = _tool_names_for_log(tools)
    logger.info(
        "react_graph init graph=%s user_id=%s tool_count=%s tool_names=%s",
        graph_name,
        user_id,
        len(tools),
        bound_tool_names,
    )
    cal_hint = [n for n in bound_tool_names if "calendar" in n.lower()]
    if not cal_hint:
        logger.warning(
            "react_graph graph=%s user_id=%s no tool name contains 'calendar' — "
            "read_calendar tools may be missing from build_agent_tools",
            graph_name,
            user_id,
        )

    def call_model(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        msgs = _repair_openai_tool_message_chain(list(state["messages"]))
        msgs = [_sanitize_message_for_llm(m) for m in msgs]
        existing_summary = (state.get("conversation_summary") or "").strip() or None

        updates: dict[str, Any] = {}
        if len(msgs) > SUMMARY_TRIGGER_MESSAGES:
            cutoff = max(len(msgs) - SUMMARY_KEEP_RECENT_MESSAGES, 0)
            chunk = msgs[:cutoff]
            chunk_text = _render_recent_messages(chunk)
            updated_summary = _summarize_chunk(
                llm=llm,
                prior_summary=existing_summary,
                chunk_text=chunk_text,
            )
            if updated_summary != existing_summary:
                updates["conversation_summary"] = updated_summary
                existing_summary = updated_summary

        recent_slice = msgs[-SUMMARY_KEEP_RECENT_MESSAGES:]
        recent_context = _render_recent_messages(recent_slice)
        tz_name, current_date, current_weekday = _current_time_context(default_timezone)
        dynamic_ctx = (
            "\n\nContext (refreshed each model call): "
            f"User timezone: {tz_name}. "
            f"Current local date: {current_date}. "
            f"Current local day of week: {current_weekday}. "
            "Resolve all relative date/day references against this local date/day context. "
            f"User email: {user_email or '—'}."
        )
        summary_ctx = chat_context_prompt(
            conversation_summary=existing_summary,
            recent_messages_context=recent_context,
        )
        combined_system = _safe_json_text(system_prompt + dynamic_ctx + summary_ctx)
        if not msgs:
            msgs = [SystemMessage(content=combined_system)]
        elif hasattr(msgs[0], "type") and msgs[0].type == "system":
            msgs = [SystemMessage(content=combined_system), *msgs[1:]]
        else:
            msgs = [SystemMessage(content=combined_system), *msgs]
        out = llm.bind_tools(tools).invoke(msgs)
        tcs = getattr(out, "tool_calls", None) or []
        if tcs:
            names = [tc.get("name") for tc in tcs]
            logger.info(
                "react_graph graph=%s user_id=%s model_tool_calls=%s",
                graph_name,
                user_id,
                names,
            )
            for tc in tcs:
                logger.debug(
                    "react_graph graph=%s tool_call name=%s args=%s",
                    graph_name,
                    tc.get("name"),
                    tc.get("args"),
                )
        else:
            text = getattr(out, "content", None)
            preview = (text if isinstance(text, str) else str(text))[:1200]
            logger.info(
                "react_graph graph=%s user_id=%s model_finished_without_tools "
                "content_preview=%r",
                graph_name,
                user_id,
                preview,
            )
        return {**updates, "messages": [out]}

    def after_tools(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        ai: AIMessage | None = None
        for m in reversed(state["messages"]):
            if isinstance(m, AIMessage) and m.tool_calls:
                ai = m
                break
        fps = fingerprint_tool_calls(ai) if ai else []
        if ai and ai.tool_calls:
            tail: list[ToolMessage] = []
            seen_ai = False
            for m in state["messages"]:
                if m is ai:
                    seen_ai = True
                    continue
                if seen_ai and isinstance(m, ToolMessage):
                    tail.append(m)
                elif seen_ai:
                    break
            for tm in tail:
                preview = (tm.content or "")[:800]
                logger.info(
                    "react_graph graph=%s user_id=%s tool_result name=%s tool_call_id=%s "
                    "content_preview=%r",
                    graph_name,
                    user_id,
                    getattr(tm, "name", None),
                    getattr(tm, "tool_call_id", None),
                    preview,
                )
        stop, merged, tr = check_tool_loop_limits(state, new_fingerprints=fps)
        if stop:
            return {
                "tool_rounds": tr,
                "tool_fingerprints": merged,
                "loop_stopped": True,
                "messages": [
                    AIMessage(
                        content=(
                            "I stopped because the tool loop limit was reached or the same "
                            "action repeated too many times. Say what you'd like next."
                        )
                    )
                ],
            }
        logger.info(
            "react_graph graph=%s user_id=%s after_tools round=%s fingerprints=%s",
            graph_name,
            user_id,
            tr,
            len(merged),
        )
        return {"tool_rounds": tr, "tool_fingerprints": merged}

    def approval_gate(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        raw = [p for p in (state.get("pending_proposals") or []) if p.get("type") != "__clear__"]
        props = _filter_proposals_by_scope(raw, proposal_types_scope)
        if not props:
            return {}
        summary = _format_approval_display(props, from_email=approval_from_email)
        resp = interrupt(
            {
                "kind": "approval",
                "proposals": props,
                "summary": summary,
                "unit": graph_name,
                "actions": [
                    {"id": "approve", "label": "Approve"},
                    {"id": "edit", "label": "Edit"},
                    {"id": "reject", "label": "Reject"},
                ],
            }
        )
        action = _parse_approval_resume(resp)
        if action == "approve":
            return {"resume_approved": True, "approval_edit_requested": False}
        if action == "edit":
            feedback = _approval_edit_feedback(resp)
            if feedback:
                return {
                    "pending_proposals": [PROPOSAL_CLEAR],
                    "resume_approved": False,
                    "approval_edit_requested": True,
                    "messages": [HumanMessage(content=feedback)],
                }
            return {
                "pending_proposals": [PROPOSAL_CLEAR],
                "resume_approved": False,
                "approval_edit_requested": False,
                "messages": [
                    AIMessage(
                        content=(
                            "Sure - tell me what you want to change in this task, "
                            "and I will update the plan before asking for approval again."
                        )
                    )
                ],
            }
        cleared = [PROPOSAL_CLEAR]
        return {
            "pending_proposals": cleared,
            "resume_approved": False,
            "approval_edit_requested": False,
            "messages": [
                AIMessage(
                    content="No calendar or email changes were applied. Tell me if you want to adjust the plan."
                )
            ],
        }

    def execute_mutations(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        raw = [p for p in (state.get("pending_proposals") or []) if p.get("type") != "__clear__"]
        props = _filter_proposals_by_scope(raw, proposal_types_scope)
        results = execute_all_proposals(
            db,
            user_id,
            settings,
            default_timezone=default_timezone,
            proposals=props,
        )
        ok_count = sum(1 for r in results if r.get("ok"))
        fail_count = len(results) - ok_count
        logger.info(
            "execute_mutations graph=%s user_id=%s proposals=%s ok=%s failed=%s",
            graph_name,
            user_id,
            len(results),
            ok_count,
            fail_count,
        )
        summary = format_execution_summary(results)
        body = summary.strip() or "Execution completed with no user-visible result details."
        messages: list[AIMessage] = [AIMessage(content=f"Executed actions:\n{body}")]
        return {
            "pending_proposals": [PROPOSAL_CLEAR],
            "resume_approved": None,
            "approval_edit_requested": False,
            "last_execution_results": results,
            "messages": messages,
        }

    def graceful_stop(
        _state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        return {}

    def _route_from_agent(state: CalendarAgentState) -> Literal["tools", "approval_gate", "__end__"]:
        dest = route_from_agent_scoped(state, proposal_types_scope=proposal_types_scope)
        n_props = len(
            [
                p
                for p in (state.get("pending_proposals") or [])
                if p.get("type") not in (None, "__clear__")
            ]
        )
        logger.info(
            "react_graph graph=%s user_id=%s route_from_agent -> %s pending_proposals=%s",
            graph_name,
            user_id,
            dest,
            n_props,
        )
        return dest

    graph = StateGraph(CalendarAgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", tool_node)
    graph.add_node("after_tools", after_tools)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("execute_mutations", execute_mutations)
    graph.add_node("graceful_stop", graceful_stop)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent",
        _route_from_agent,
        {
            "tools": "tools",
            "approval_gate": "approval_gate",
            "__end__": END,
        },
    )
    graph.add_edge("tools", "after_tools")
    graph.add_conditional_edges(
        "after_tools",
        route_after_tools,
        {
            "graceful_stop": "graceful_stop",
            "agent": "agent",
            "end_turn": END,
        },
    )
    graph.add_edge("graceful_stop", END)

    graph.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {
            "execute_mutations": "execute_mutations",
            "agent": "agent",
            "__end__": END,
        },
    )
    graph.add_edge("execute_mutations", END)

    return graph.compile(checkpointer=checkpointer)
