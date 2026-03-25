"""Routing helpers and limits for the calendar assistant graph."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from langchain_core.messages import AIMessage

# Tunables (could move to Settings later)
MAX_TOOL_ROUNDS_PER_TURN = 15
MAX_SAME_FINGERPRINT_STRIKES = 3


def route_after_tools(state: dict) -> Literal["graceful_stop", "agent", "end_turn"]:
    """Backward-compatible single-agent router after ToolNode."""
    out = route_after_tools_domain(state)
    if out == "graceful_stop":
        return "graceful_stop"
    if out == "return_to_main":
        return "end_turn"
    return "agent"


def route_after_tools_domain(
    state: dict,
) -> Literal["graceful_stop", "return_to_main", "continue_domain"]:
    """
    Domain-aware router after ToolNode.

    - graceful_stop: loop guard triggered.
    - return_to_main: clarification-only turn should return to main router/end turn.
    - continue_domain: continue the current domain loop.
    """
    if state.get("loop_stopped"):
        return "graceful_stop"
    if _last_ai_tool_calls_were_only_clarification(state):
        return "return_to_main"
    return "continue_domain"


def _last_ai_tool_calls_were_only_clarification(state: dict) -> bool:
    """True when the latest tool-calling turn only invoked ``request_user_clarification``."""
    for m in reversed(state.get("messages") or []):
        if isinstance(m, AIMessage) and m.tool_calls:
            names = [tc.get("name") for tc in (m.tool_calls or [])]
            return len(names) == 1 and names[0] == "request_user_clarification"
    return False


def route_post_agent(state: dict) -> Literal["approval_gate", "__end__"]:
    """When the model stops calling tools: require approval if there are proposals."""
    props = [
        p
        for p in (state.get("pending_proposals") or [])
        if p.get("type") not in (None, "__clear__")
    ]
    if props:
        return "approval_gate"
    return "__end__"


def route_after_approval(state: dict) -> Literal["execute_mutations", "agent", "__end__"]:
    """Backward-compatible single-agent router after approval gate."""
    out = route_after_approval_domain(state)
    if out == "execute_mutations":
        return "execute_mutations"
    if out == "continue_domain":
        return "agent"
    return "__end__"


def route_after_approval_domain(
    state: dict,
) -> Literal["execute_mutations", "continue_domain", "return_to_main"]:
    """Domain-aware router after approval gate."""
    if state.get("resume_approved") is True:
        return "execute_mutations"
    if state.get("approval_edit_requested"):
        return "continue_domain"
    return "return_to_main"


def fingerprint_tool_calls(ai: AIMessage) -> list[str]:
    fps: list[str] = []
    for tc in ai.tool_calls or []:
        name = tc.get("name", "")
        args = tc.get("args") or {}
        raw = f"{name}:{json.dumps(args, sort_keys=True, default=str)}"
        fps.append(hashlib.sha256(raw.encode()).hexdigest()[:16])
    return fps


def check_tool_loop_limits(
    state: dict,
    *,
    new_fingerprints: list[str],
) -> tuple[bool, list[str], int]:
    """
    Increment tool round and detect runaway loops.

    Returns (should_stop, updated_fingerprints_list, tool_rounds).
    """
    tr = int(state.get("tool_rounds", 0)) + 1
    prev_fps: list[str] = list(state.get("tool_fingerprints") or [])
    merged = (prev_fps + new_fingerprints)[-40:]

    should_stop = False
    if tr > MAX_TOOL_ROUNDS_PER_TURN:
        should_stop = True
    for fp in set(new_fingerprints):
        if merged.count(fp) >= MAX_SAME_FINGERPRINT_STRIKES:
            should_stop = True
            break

    return should_stop, merged, tr