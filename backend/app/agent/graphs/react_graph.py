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
    route_after_approval_domain,
    route_after_tools_domain,
)
from app.agent.graphs.state import (
    MAX_MESSAGES_STATE,
    MIN_MESSAGES_AFTER_SUMMARIZATION,
    PROPOSAL_CLEAR,
    REPLACE_MESSAGES_KEY,
    CalendarAgentState,
)
from app.agent.prompts import chat_context_prompt
from app.agent.tools.execution import execute_all_proposals, format_execution_summary
from app.agent.tools.proposals_calendar import CALENDAR_PROPOSAL_TYPES
from app.agent.tools.proposals_gmail import GMAIL_PROPOSAL_TYPES
from app.config import Settings

logger = logging.getLogger(__name__)


def _now_rfc3339_in_tz(tz_name: str) -> str:
    try:
        z = ZoneInfo(tz_name)
    except Exception:
        z = ZoneInfo("UTC")
    return datetime.now(z).isoformat()


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
    main_system_prompt: str | None = None,
    email_system_prompt: str | None = None,
    calendar_system_prompt: str | None = None,
):
    """
    Compile a ReAct-style graph with optional proposal scope.

    If ``proposal_types_scope`` is set (standalone unit subgraph), approval and execution
    only consider proposals whose ``type`` is in the set. The main combined graph passes
    ``None`` to handle calendar + Gmail proposals together.
    """
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

    def _domain_default() -> Literal["email_agent", "calendar_agent", "__end__"]:
        if proposal_types_scope == GMAIL_PROPOSAL_TYPES:
            return "email_agent"
        if proposal_types_scope == CALENDAR_PROPOSAL_TYPES:
            return "calendar_agent"
        low = graph_name.lower()
        if "gmail" in low or "email" in low:
            return "email_agent"
        if "calendar" in low:
            return "calendar_agent"
        return "calendar_agent"

    def _tool_name(tool_obj: Any) -> str:
        n = getattr(tool_obj, "name", None)
        if callable(n):
            try:
                n = n()
            except Exception:
                n = None
        if n is None and hasattr(tool_obj, "get_name"):
            try:
                n = tool_obj.get_name()  # type: ignore[union-attr]
            except Exception:
                n = None
        return n if isinstance(n, str) else ""

    def _is_email_tool_name(name: str) -> bool:
        low = name.lower()
        return any(tok in low for tok in ("email", "gmail", "draft"))

    def _is_calendar_tool_name(name: str) -> bool:
        low = name.lower()
        return any(tok in low for tok in ("calendar", "event", "meeting", "busy", "conflict"))

    def _partition_domain_tools(all_tools: list[Any]) -> tuple[list[Any], list[Any]]:
        email_domain_tools: list[Any] = []
        calendar_domain_tools: list[Any] = []
        for t in all_tools:
            name = _tool_name(t)
            if name == "request_user_clarification":
                email_domain_tools.append(t)
                calendar_domain_tools.append(t)
                continue
            is_email = _is_email_tool_name(name)
            is_calendar = _is_calendar_tool_name(name)
            if is_email:
                email_domain_tools.append(t)
            if is_calendar:
                calendar_domain_tools.append(t)
            if not is_email and not is_calendar:
                # Keep unknown tools reachable while preserving domain fanout.
                email_domain_tools.append(t)
                calendar_domain_tools.append(t)
        return email_domain_tools, calendar_domain_tools

    email_tools, calendar_tools = _partition_domain_tools(tools)
    email_tool_node = ToolNode(email_tools)
    calendar_tool_node = ToolNode(calendar_tools)

    def _has_action_tools(domain_tools: list[Any]) -> bool:
        for t in domain_tools:
            if _tool_name(t) != "request_user_clarification":
                return True
        return False

    email_available = _has_action_tools(email_tools)
    calendar_available = _has_action_tools(calendar_tools)
    logger.info(
        "react_graph graph=%s user_id=%s domain_tools email=%s calendar=%s",
        graph_name,
        user_id,
        _tool_names_for_log(email_tools),
        _tool_names_for_log(calendar_tools),
    )

    resolved_main_prompt = main_system_prompt or system_prompt
    resolved_email_prompt = email_system_prompt or system_prompt
    resolved_calendar_prompt = calendar_system_prompt or system_prompt

    def _invoke_domain_model(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        msgs = _repair_openai_tool_message_chain(list(state["messages"]))
        existing_summary = (state.get("conversation_summary") or "").strip() or None

        updates: dict[str, Any] = {}
        compacted_recent: list[Any] | None = None
        if len(msgs) > MAX_MESSAGES_STATE:
            chunk = msgs[:MAX_MESSAGES_STATE]
            chunk_text = _render_recent_messages(chunk)
            updated_summary = _summarize_chunk(
                llm=llm,
                prior_summary=existing_summary,
                chunk_text=chunk_text,
            )
            if updated_summary != existing_summary:
                updates["conversation_summary"] = updated_summary
                existing_summary = updated_summary
            compacted_recent = list(msgs[-MIN_MESSAGES_AFTER_SUMMARIZATION:])
            while compacted_recent and getattr(compacted_recent[0], "type", None) == "tool":
                compacted_recent.pop(0)
            msgs = compacted_recent

        recent_context = _render_recent_messages(msgs)
        now_iso = _now_rfc3339_in_tz(default_timezone)
        dynamic_ctx = (
            f"\n\nContext (refreshed each model call): "
            f"Current local time for the user ({default_timezone}): {now_iso}. "
            f"User email: {user_email or '—'}."
        )
        summary_ctx = chat_context_prompt(
            conversation_summary=existing_summary,
            recent_messages_context=recent_context,
        )
        domain = (config or {}).get("configurable", {}).get("domain", "unknown")
        domain_tools = tools
        domain_prompt = resolved_calendar_prompt
        if domain == "email":
            domain_tools = email_tools
            domain_prompt = resolved_email_prompt
        elif domain == "calendar":
            domain_tools = calendar_tools
            domain_prompt = resolved_calendar_prompt

        combined_system = domain_prompt + dynamic_ctx + summary_ctx
        if not msgs:
            msgs = [SystemMessage(content=combined_system)]
        elif hasattr(msgs[0], "type") and msgs[0].type == "system":
            msgs = [SystemMessage(content=combined_system), *msgs[1:]]
        else:
            msgs = [SystemMessage(content=combined_system), *msgs]

        out = llm.bind_tools(domain_tools).invoke(msgs)
        tcs = getattr(out, "tool_calls", None) or []
        if tcs:
            names = [tc.get("name") for tc in tcs]
            logger.info(
                "react_graph graph=%s user_id=%s domain=%s model_tool_calls=%s",
                graph_name,
                user_id,
                domain,
                names,
            )
            for tc in tcs:
                logger.debug(
                    "react_graph graph=%s domain=%s tool_call name=%s args=%s",
                    graph_name,
                    domain,
                    tc.get("name"),
                    tc.get("args"),
                )
        else:
            text = getattr(out, "content", None)
            preview = (text if isinstance(text, str) else str(text))[:1200]
            logger.info(
                "react_graph graph=%s user_id=%s domain=%s model_finished_without_tools "
                "content_preview=%r",
                graph_name,
                user_id,
                domain,
                preview,
            )
        if compacted_recent is not None:
            return {
                **updates,
                "messages": [
                    {REPLACE_MESSAGES_KEY: True, "messages": compacted_recent},
                    out,
                ],
            }
        return {**updates, "messages": [out]}

    def call_main_agent(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        latest_human = _latest_human_with_index(state)
        if latest_human is None:
            return {"task_agent_route": "__end__"}

        human_idx, text = latest_human
        text = text.strip()
        if not text:
            return {"task_agent_route": "__end__"}

        existing_plan = _normalize_plan_steps(state.get("task_agent_plan") or [])
        existing_idx = int(state.get("task_agent_plan_index", 0) or 0)
        existing_source_idx = state.get("task_agent_plan_source_human_idx")
        is_same_turn = existing_source_idx == human_idx

        if is_same_turn and existing_idx < len(existing_plan):
            decision = existing_plan[existing_idx]
            logger.info(
                "react_graph graph=%s user_id=%s main_plan_continue step=%s/%s route=%s",
                graph_name,
                user_id,
                existing_idx + 1,
                len(existing_plan),
                decision,
            )
            return {
                "task_agent_route": decision,
                "task_agent_plan": existing_plan,
                "task_agent_plan_index": existing_idx + 1,
                "task_agent_plan_source_human_idx": human_idx,
            }
        if is_same_turn:
            return {"task_agent_route": "__end__"}

        planning_prompt = (
            f"{resolved_main_prompt}\n\n"
            "Create an execution plan using only these domain steps:\n"
            "- calendar_agent\n"
            "- email_agent\n\n"
            "Rules:\n"
            "1) Include each domain at most once.\n"
            "2) Order steps by dependency. If an email depends on calendar actions, calendar_agent must come first.\n"
            "3) Return strict JSON only, no prose.\n"
            'Format: {"steps":["calendar_agent","email_agent"]}\n'
            'Use {"steps":[]} when no domain work is needed.'
        )
        plan_steps: list[Literal["email_agent", "calendar_agent"]] = []
        try:
            out = llm.invoke(
                [
                    SystemMessage(content=planning_prompt),
                    HumanMessage(content=text),
                ]
            )
            payload = _message_content_text(out).strip()
            parsed = json.loads(payload)
            plan_steps = _normalize_plan_steps(parsed.get("steps") if isinstance(parsed, dict) else [])
        except Exception:
            plan_steps = []

        if not plan_steps:
            plan_steps = _heuristic_plan_for_text(text)
        if not email_available:
            plan_steps = [s for s in plan_steps if s != "email_agent"]
        if not calendar_available:
            plan_steps = [s for s in plan_steps if s != "calendar_agent"]

        if not plan_steps:
            logger.info(
                "react_graph graph=%s user_id=%s main_plan_new steps=[]",
                graph_name,
                user_id,
            )
            return {
                "task_agent_route": "__end__",
                "task_agent_plan": [],
                "task_agent_plan_index": 0,
                "task_agent_plan_source_human_idx": human_idx,
            }

        decision = plan_steps[0]
        logger.info(
            "react_graph graph=%s user_id=%s main_plan_new steps=%s first=%s",
            graph_name,
            user_id,
            plan_steps,
            decision,
        )
        return {
            "task_agent_route": decision,
            "task_agent_plan": plan_steps,
            "task_agent_plan_index": 1,
            "task_agent_plan_source_human_idx": human_idx,
        }

    def call_email_model(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        cfg = dict(config or {})
        configurable = dict(cfg.get("configurable", {}))
        configurable["domain"] = "email"
        cfg["configurable"] = configurable
        return _invoke_domain_model(state, config=cfg)

    def call_calendar_model(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        cfg = dict(config or {})
        configurable = dict(cfg.get("configurable", {}))
        configurable["domain"] = "calendar"
        cfg["configurable"] = configurable
        return _invoke_domain_model(state, config=cfg)

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

    def _approval_gate_for_scope(
        state: CalendarAgentState,
        config: RunnableConfig | None = None,
        *,
        unit_name: str,
        scope: frozenset[str] | None,
    ) -> dict[str, Any]:
        raw = [p for p in (state.get("pending_proposals") or []) if p.get("type") != "__clear__"]
        props = _filter_proposals_by_scope(raw, scope)
        if not props:
            return {}
        summary = _format_approval_display(props, from_email=approval_from_email)
        resp = interrupt(
            {
                "kind": "approval",
                "proposals": props,
                "summary": summary,
                "unit": unit_name,
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

    def email_approval_gate(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        return _approval_gate_for_scope(
            state,
            config=config,
            unit_name="email",
            scope=GMAIL_PROPOSAL_TYPES,
        )

    def calendar_approval_gate(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        return _approval_gate_for_scope(
            state,
            config=config,
            unit_name="calendar",
            scope=CALENDAR_PROPOSAL_TYPES,
        )

    def _execute_mutations_for_scope(
        state: CalendarAgentState,
        config: RunnableConfig | None = None,
        *,
        scope: frozenset[str] | None,
    ) -> dict[str, Any]:
        raw = [p for p in (state.get("pending_proposals") or []) if p.get("type") != "__clear__"]
        props = _filter_proposals_by_scope(raw, scope)
        results = execute_all_proposals(
            db,
            user_id,
            settings,
            default_timezone=default_timezone,
            proposals=props,
        )
        summary = format_execution_summary(results)
        return {
            "pending_proposals": [PROPOSAL_CLEAR],
            "resume_approved": None,
            "approval_edit_requested": False,
            "last_execution_results": results,
            "messages": [AIMessage(content=f"Executed actions:\n{summary}")],
        }

    def execute_email_mutations(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        return _execute_mutations_for_scope(
            state,
            config=config,
            scope=GMAIL_PROPOSAL_TYPES,
        )

    def execute_calendar_mutations(
        state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        return _execute_mutations_for_scope(
            state,
            config=config,
            scope=CALENDAR_PROPOSAL_TYPES,
        )

    def graceful_stop(
        _state: CalendarAgentState, config: RunnableConfig | None = None
    ) -> dict[str, Any]:
        return {}

    def _latest_human_text(state: CalendarAgentState) -> str:
        for m in reversed(state.get("messages") or []):
            if isinstance(m, HumanMessage):
                return _message_content_text(m)
        return ""

    def _latest_human_with_index(state: CalendarAgentState) -> tuple[int, str] | None:
        msgs = state.get("messages") or []
        for idx in range(len(msgs) - 1, -1, -1):
            m = msgs[idx]
            if isinstance(m, HumanMessage):
                return idx, _message_content_text(m)
        return None

    def _normalize_plan_steps(raw_steps: Any) -> list[Literal["email_agent", "calendar_agent"]]:
        out: list[Literal["email_agent", "calendar_agent"]] = []
        for raw in raw_steps if isinstance(raw_steps, list) else []:
            s = str(raw).strip().lower()
            if s in {"email_agent", "email", "gmail"} and "email_agent" not in out:
                out.append("email_agent")
            elif s in {"calendar_agent", "calendar"} and "calendar_agent" not in out:
                out.append("calendar_agent")
        return out

    def _heuristic_plan_for_text(text: str) -> list[Literal["email_agent", "calendar_agent"]]:
        low = text.lower()
        email_score = sum(
            1
            for tok in ("email", "gmail", "inbox", "draft", "subject", "send mail", "compose", "notify")
            if tok in low
        )
        calendar_score = sum(
            1
            for tok in ("calendar", "event", "meeting", "schedule", "reschedule", "time slot", "busy", "call")
            if tok in low
        )
        if email_score > 0 and calendar_score > 0:
            return ["calendar_agent", "email_agent"]
        if calendar_score > 0:
            return ["calendar_agent"]
        if email_score > 0:
            return ["email_agent"]
        return []

    def _latest_conversation_message(state: CalendarAgentState) -> Any | None:
        for m in reversed(state.get("messages") or []):
            if isinstance(m, (AIMessage, HumanMessage, ToolMessage)):
                return m
        return None

    def _route_to_task_agent(
        state: CalendarAgentState,
    ) -> Literal["email_agent", "calendar_agent", "__end__"]:
        route_hint = state.get("task_agent_route")
        if route_hint in {"email_agent", "calendar_agent", "__end__"}:
            return route_hint
        latest_msg = _latest_conversation_message(state)
        if not isinstance(latest_msg, HumanMessage):
            return "__end__"

        if not email_available and not calendar_available:
            return "__end__"
        if email_available and not calendar_available:
            return "email_agent"
        if calendar_available and not email_available:
            return "calendar_agent"

        pending = [p for p in (state.get("pending_proposals") or []) if p.get("type") not in (None, "__clear__")]
        if any(p.get("type") in GMAIL_PROPOSAL_TYPES for p in pending):
            return "email_agent"
        if any(p.get("type") in CALENDAR_PROPOSAL_TYPES for p in pending):
            return "calendar_agent"

        text = _latest_human_text(state).lower()
        email_score = sum(
            1
            for tok in ("email", "gmail", "inbox", "draft", "subject", "send mail", "compose")
            if tok in text
        )
        calendar_score = sum(
            1
            for tok in ("calendar", "event", "meeting", "schedule", "reschedule", "time slot", "busy")
            if tok in text
        )
        if email_score > calendar_score:
            return "email_agent"
        if calendar_score > email_score:
            return "calendar_agent"
        return _domain_default()

    def _route_from_agent_for_scope(
        state: CalendarAgentState, *, scope: frozenset[str] | None
    ) -> Literal["tools", "approval_gate", "__end__"]:
        dest = route_from_agent_scoped(state, proposal_types_scope=scope)
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

    def _route_from_email_agent(
        state: CalendarAgentState,
    ) -> Literal["email_tools", "email_approval_gate", "main_agent"]:
        out = _route_from_agent_for_scope(state, scope=GMAIL_PROPOSAL_TYPES)
        if out == "tools":
            return "email_tools"
        if out == "approval_gate":
            return "email_approval_gate"
        return "main_agent"

    def _route_from_calendar_agent(
        state: CalendarAgentState,
    ) -> Literal["calendar_tools", "calendar_approval_gate", "main_agent"]:
        out = _route_from_agent_for_scope(state, scope=CALENDAR_PROPOSAL_TYPES)
        if out == "tools":
            return "calendar_tools"
        if out == "approval_gate":
            return "calendar_approval_gate"
        return "main_agent"

    def _route_after_email_tools(
        state: CalendarAgentState,
    ) -> Literal["graceful_stop", "email_agent", "main_agent"]:
        out = route_after_tools_domain(state)
        if out == "graceful_stop":
            return "graceful_stop"
        if out == "continue_domain":
            return "email_agent"
        return "main_agent"

    def _route_after_calendar_tools(
        state: CalendarAgentState,
    ) -> Literal["graceful_stop", "calendar_agent", "main_agent"]:
        out = route_after_tools_domain(state)
        if out == "graceful_stop":
            return "graceful_stop"
        if out == "continue_domain":
            return "calendar_agent"
        return "main_agent"

    def _route_after_email_approval(
        state: CalendarAgentState,
    ) -> Literal["execute_email_mutations", "email_agent", "main_agent"]:
        out = route_after_approval_domain(state)
        if out == "execute_mutations":
            return "execute_email_mutations"
        if out == "continue_domain":
            return "email_agent"
        return "main_agent"

    def _route_after_calendar_approval(
        state: CalendarAgentState,
    ) -> Literal["execute_calendar_mutations", "calendar_agent", "main_agent"]:
        out = route_after_approval_domain(state)
        if out == "execute_mutations":
            return "execute_calendar_mutations"
        if out == "continue_domain":
            return "calendar_agent"
        return "main_agent"

    graph = StateGraph(CalendarAgentState)
    graph.add_node("main_agent", call_main_agent)
    graph.add_node("email_agent", call_email_model)
    graph.add_node("calendar_agent", call_calendar_model)
    graph.add_node("email_tools", email_tool_node)
    graph.add_node("calendar_tools", calendar_tool_node)
    graph.add_node("email_after_tools", after_tools)
    graph.add_node("calendar_after_tools", after_tools)
    graph.add_node("email_approval_gate", email_approval_gate)
    graph.add_node("calendar_approval_gate", calendar_approval_gate)
    graph.add_node("execute_email_mutations", execute_email_mutations)
    graph.add_node("execute_calendar_mutations", execute_calendar_mutations)
    graph.add_node("graceful_stop", graceful_stop)

    graph.add_edge(START, "main_agent")
    graph.add_conditional_edges(
        "main_agent",
        _route_to_task_agent,
        {
            "email_agent": "email_agent",
            "calendar_agent": "calendar_agent",
            "__end__": END,
        },
    )

    graph.add_conditional_edges(
        "email_agent",
        _route_from_email_agent,
        {
            "email_tools": "email_tools",
            "email_approval_gate": "email_approval_gate",
            "main_agent": "main_agent",
        },
    )
    graph.add_conditional_edges(
        "calendar_agent",
        _route_from_calendar_agent,
        {
            "calendar_tools": "calendar_tools",
            "calendar_approval_gate": "calendar_approval_gate",
            "main_agent": "main_agent",
        },
    )

    graph.add_edge("email_tools", "email_after_tools")
    graph.add_edge("calendar_tools", "calendar_after_tools")
    graph.add_conditional_edges(
        "email_after_tools",
        _route_after_email_tools,
        {
            "graceful_stop": "graceful_stop",
            "email_agent": "email_agent",
            "main_agent": "main_agent",
        },
    )
    graph.add_conditional_edges(
        "calendar_after_tools",
        _route_after_calendar_tools,
        {
            "graceful_stop": "graceful_stop",
            "calendar_agent": "calendar_agent",
            "main_agent": "main_agent",
        },
    )

    graph.add_conditional_edges(
        "email_approval_gate",
        _route_after_email_approval,
        {
            "execute_email_mutations": "execute_email_mutations",
            "email_agent": "email_agent",
            "main_agent": "main_agent",
        },
    )
    graph.add_conditional_edges(
        "calendar_approval_gate",
        _route_after_calendar_approval,
        {
            "execute_calendar_mutations": "execute_calendar_mutations",
            "calendar_agent": "calendar_agent",
            "main_agent": "main_agent",
        },
    )
    graph.add_edge("execute_email_mutations", "main_agent")
    graph.add_edge("execute_calendar_mutations", "main_agent")
    graph.add_edge("graceful_stop", END)

    return graph.compile(checkpointer=checkpointer)
