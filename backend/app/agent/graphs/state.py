"""
LangGraph state for the calendar assistant (messages, proposals, HITL, loop guards).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.graph.message import add_messages
from typing_extensions import Required

MAX_MESSAGES_STATE = 20  # maximum messages before summary+compaction
MIN_MESSAGES_AFTER_SUMMARIZATION = 10  # retain this many recent messages after compaction


PROPOSAL_CLEAR: dict[str, Any] = {"type": "__clear__", "id": ""}
REPLACE_MESSAGES_KEY = "__replace_messages__"


def reduce_pending_proposals(
    existing: list[dict[str, Any]] | None,
    new_items: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """
    Append proposals; if a sentinel `{type: '__clear__'}` appears, reset the list.
    """
    acc = list(existing or [])
    for item in new_items or []:
        if item.get("type") == "__clear__":
            acc = []
        else:
            acc.append(item)
    return acc


def reduce_messages_bounded(
    existing: list[Any] | None,
    new_items: list[Any] | None,
) -> list[Any]:
    """
    Append messages by default.
    Supports replacement mode when first new item is:
    { "__replace_messages__": True, "messages": [...] }.
    """
    incoming = list(new_items or [])
    base = list(existing or [])

    if incoming and isinstance(incoming[0], dict) and incoming[0].get(REPLACE_MESSAGES_KEY):
        replacement = incoming[0].get("messages") or []
        if isinstance(replacement, list):
            base = list(replacement)
        incoming = incoming[1:]

    merged = add_messages(base, incoming)
    trimmed = list(merged)
    while trimmed and getattr(trimmed[0], "type", None) == "tool":
        trimmed.pop(0)
    return trimmed


# --- Proposal payloads (stored as dicts; executed in execution.py) ---

ProposalType = Literal[
    "create_event",
    "update_event",
    "delete_event",
    "create_email_draft",
    "send_email",
]


class BaseProposal(TypedDict):
    type: ProposalType
    id: str
    """Stable id for idempotency / UI keys (uuid)."""


class CreateEventProposal(BaseProposal):
    type: Literal["create_event"]
    summary: str
    start_datetime: str
    end_datetime: str
    timezone: str
    description: str | None
    calendar_id: str
    attendees: str
    """Comma-separated participant emails (required for create)."""


class UpdateEventProposal(BaseProposal):
    type: Literal["update_event"]
    event_id: str
    summary: str | None
    description: str | None
    start_datetime: str | None
    end_datetime: str | None
    timezone: str | None
    calendar_id: str
    attendees: str | None


class DeleteEventProposal(BaseProposal):
    type: Literal["delete_event"]
    event_id: str
    calendar_id: str


class CreateDraftProposal(BaseProposal):
    type: Literal["create_email_draft"]
    to: str
    subject: str
    body: str


class SendEmailProposal(BaseProposal):
    type: Literal["send_email"]
    to: str
    subject: str
    body: str


CalendarProposal = (
    CreateEventProposal
    | UpdateEventProposal
    | DeleteEventProposal
    | CreateDraftProposal
    | SendEmailProposal
)


class CalendarAgentState(TypedDict):
    """Graph state: conversation, pending mutations, HITL, and safety counters."""

    messages: Annotated[list[Any], reduce_messages_bounded]
    pending_proposals: Annotated[list[dict[str, Any]], reduce_pending_proposals]
    """Mutation proposals queued until user approves (cleared via __clear__ sentinel)."""
    conversation_summary: NotRequired[str | None]
    """
    Rolling summary of older turns, refreshed when recent message count exceeds threshold.
    """

    clarification_prompt: NotRequired[str | None]
    """Legacy; clarification is now an in-chat ``AIMessage`` (no interrupt)."""

    approval_summary: NotRequired[str | None]
    """Human-readable summary shown with approval interrupt."""

    tool_rounds: int
    """Tool executions (ToolNode invocations) in the current user turn."""

    tool_fingerprints: list[str]
    """Recent tool name+args hashes for deduplication (updated in tool routing)."""

    loop_stopped: NotRequired[bool]
    """Set when limits hit; routing ends the turn."""

    last_execution_results: NotRequired[list[dict[str, Any]] | None]
    """Structured results from execute_mutations for optional UI / logging."""

    resume_approved: NotRequired[bool | None]
    """Set by approval_gate after user confirms or rejects pending proposals."""
    approval_edit_requested: NotRequired[bool]
    """Set when user selects edit so routing returns to agent with user feedback."""
    task_agent_route: NotRequired[Literal["email_agent", "calendar_agent", "__end__"]]
    """Transient main-router decision used by hierarchical fanout."""
    task_agent_plan: NotRequired[list[Literal["email_agent", "calendar_agent"]]]
    """Ordered domain execution plan for the current user turn."""
    task_agent_plan_index: NotRequired[int]
    """Next step index into task_agent_plan."""
    task_agent_plan_source_human_idx: NotRequired[int]
    """Index of the human message used to build the current plan."""


class GraphContext(TypedDict, total=False):
    """Passed via RunnableConfig `context` for tools and nodes."""

    user_id: Required[int]
    default_timezone: Required[str]
