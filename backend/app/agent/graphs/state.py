"""
LangGraph state for the calendar assistant (messages, proposals, HITL, loop guards).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.graph.message import add_messages
from typing_extensions import Required

MAX_MESSAGES_STATE = 40
SUMMARY_TRIGGER_MESSAGES = 30
SUMMARY_KEEP_RECENT_MESSAGES = 16


PROPOSAL_CLEAR: dict[str, Any] = {"type": "__clear__", "id": ""}


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
    """Append messages, keep a bounded window, and avoid orphan leading tool messages."""
    merged = add_messages(existing or [], new_items or [])
    if len(merged) <= MAX_MESSAGES_STATE:
        return merged
    trimmed = list(merged[-MAX_MESSAGES_STATE:])
    # If truncation cuts off a parent AI tool_call message, drop orphan leading tool messages.
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


class GraphContext(TypedDict, total=False):
    """Passed via RunnableConfig `context` for tools and nodes."""

    user_id: Required[int]
    default_timezone: Required[str]
