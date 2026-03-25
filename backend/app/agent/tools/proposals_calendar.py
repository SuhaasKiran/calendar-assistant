"""Calendar proposal tools (queue mutations until approval)."""

import uuid

from googleapiclient.errors import HttpError
from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.agent.tools.common import format_tool_error
from app.agent.tools.read_calendar import check_window_conflicts_payload
from app.agent.tools.tool_schema import args_schema_excluding_runtime
from app.config import Settings
from app.services import calendar_client

CALENDAR_PROPOSAL_TYPES = frozenset({"create_event", "update_event", "delete_event"})


def _load_event(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    event_id: str,
    calendar_id: str,
) -> tuple[dict | None, str | None]:
    """Load an event for display/planning; returns (event, error)."""
    try:
        ev = calendar_client.get_event(
            db, user_id, settings, event_id=event_id, calendar_id=calendar_id
        )
        return ev, None
    except HttpError as e:
        if getattr(e.resp, "status", None) == 404:
            return (
                None,
                f"No calendar event exists for id {event_id!r} in calendar {calendar_id!r}. "
                "Use list_calendar_events or get_calendar_event to obtain a valid id.",
            )
        return None, format_tool_error(e)
    except Exception as e:
        return None, format_tool_error(e)


def _event_to_proposal_fields(ev: dict) -> dict:
    start = (ev.get("start") or {}) if isinstance(ev.get("start"), dict) else {}
    end = (ev.get("end") or {}) if isinstance(ev.get("end"), dict) else {}
    attendees = ev.get("attendees") if isinstance(ev.get("attendees"), list) else []
    participant_emails = ", ".join(
        str(a.get("email")).strip()
        for a in attendees
        if isinstance(a, dict) and str(a.get("email") or "").strip()
    )
    return {
        "summary": ev.get("summary"),
        "description": ev.get("description"),
        "start_datetime": start.get("dateTime") or start.get("date"),
        "end_datetime": end.get("dateTime") or end.get("date"),
        "timezone": start.get("timeZone") or end.get("timeZone"),
        "attendees": participant_emails or None,
        "event_link": ev.get("htmlLink"),
    }


def build_calendar_proposal_tools(
    db: Session,
    user_id: int,
    settings: Settings,
) -> list:
    """Tools that queue calendar mutations."""

    def propose_create_calendar_event(
        summary: str,
        start_datetime: str,
        end_datetime: str,
        timezone: str,
        attendees: str,
        runtime: ToolRuntime,
        description: str | None = None,
        calendar_id: str = "primary",
    ) -> Command:
        """Queue creating a calendar event (requires user approval). Requires RFC3339 start/end, IANA timezone, and comma-separated participant emails. Conflicts on the user's calendar block queueing."""
        err = _validate_create_fields(
            summary=summary,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timezone=timezone,
            attendees=attendees,
        )
        if err:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=err,
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        has_conflict, conflict_payload = check_window_conflicts_payload(
            db,
            user_id,
            settings,
            time_min=start_datetime.strip(),
            time_max=end_datetime.strip(),
            calendar_id=calendar_id,
        )
        if has_conflict is None:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Could not check calendar conflicts before scheduling. "
                                f"{conflict_payload}"
                            ),
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        if has_conflict:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "This time window overlaps existing events on the user's "
                                "calendar. Do not queue until resolved. Details:\n"
                                f"{conflict_payload}"
                            ),
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        pid = str(uuid.uuid4())
        proposal: dict = {
            "type": "create_event",
            "id": pid,
            "summary": summary.strip(),
            "start_datetime": start_datetime.strip(),
            "end_datetime": end_datetime.strip(),
            "timezone": timezone.strip(),
            "description": description.strip() if description else None,
            "calendar_id": calendar_id,
            "attendees": attendees.strip(),
            "create_meet_link": True,
        }
        return Command(
            update={
                "pending_proposals": [proposal],
                "messages": [
                    ToolMessage(
                        content=(
                            f"Queued proposal to create event {pid!r}. "
                            "It will run only after the user approves."
                        ),
                        tool_call_id=runtime.tool_call_id or "",
                    )
                ],
            }
        )

    def propose_create_google_meet_meeting(
        summary: str,
        start_datetime: str,
        end_datetime: str,
        timezone: str,
        attendees: str,
        runtime: ToolRuntime,
        description: str | None = None,
        calendar_id: str = "primary",
    ) -> Command:
        """Queue creating a Google Meet meeting (calendar event + Meet link) that runs only after approval."""
        err = _validate_create_fields(
            summary=summary,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            timezone=timezone,
            attendees=attendees,
        )
        if err:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=err,
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        has_conflict, conflict_payload = check_window_conflicts_payload(
            db,
            user_id,
            settings,
            time_min=start_datetime.strip(),
            time_max=end_datetime.strip(),
            calendar_id=calendar_id,
        )
        if has_conflict is None:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Could not check calendar conflicts before scheduling. "
                                f"{conflict_payload}"
                            ),
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        if has_conflict:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "This time window overlaps existing events on the user's "
                                "calendar. Do not queue until resolved. Details:\n"
                                f"{conflict_payload}"
                            ),
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        pid = str(uuid.uuid4())
        proposal: dict = {
            "type": "create_event",
            "id": pid,
            "summary": summary.strip(),
            "start_datetime": start_datetime.strip(),
            "end_datetime": end_datetime.strip(),
            "timezone": timezone.strip(),
            "description": description.strip() if description else None,
            "calendar_id": calendar_id,
            "attendees": attendees.strip(),
            "create_meet_link": True,
        }
        return Command(
            update={
                "pending_proposals": [proposal],
                "messages": [
                    ToolMessage(
                        content=(
                            f"Queued proposal to create Google Meet meeting {pid!r}. "
                            "It will run only after the user approves."
                        ),
                        tool_call_id=runtime.tool_call_id or "",
                    )
                ],
            }
        )

    def propose_update_calendar_event(
        event_id: str,
        runtime: ToolRuntime,
        summary: str | None = None,
        description: str | None = None,
        start_datetime: str | None = None,
        end_datetime: str | None = None,
        timezone: str | None = None,
        calendar_id: str = "primary",
        attendees: str | None = None,
    ) -> Command:
        """Queue updating an event that already exists on Google Calendar. If changing times, pass both start and end RFC3339 datetimes."""
        eid = event_id.strip()
        existing, missing = _load_event(
            db, user_id, settings, event_id=eid, calendar_id=calendar_id
        )
        if missing or not existing:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=missing or "Unable to load existing event.",
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        if (start_datetime is None) ^ (end_datetime is None):
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content="Error: provide both start_datetime and end_datetime when changing time.",
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        pid = str(uuid.uuid4())
        existing_fields = _event_to_proposal_fields(existing)
        proposal: dict = {
            "type": "update_event",
            "id": pid,
            "event_id": eid,
            # Show final values in approval UI: requested updates override existing values.
            "summary": summary if summary is not None else existing_fields.get("summary"),
            "description": (
                description if description is not None else existing_fields.get("description")
            ),
            "start_datetime": (
                start_datetime
                if start_datetime is not None
                else existing_fields.get("start_datetime")
            ),
            "end_datetime": (
                end_datetime if end_datetime is not None else existing_fields.get("end_datetime")
            ),
            "timezone": timezone if timezone is not None else existing_fields.get("timezone"),
            "calendar_id": calendar_id,
            "attendees": attendees if attendees is not None else existing_fields.get("attendees"),
        }
        return Command(
            update={
                "pending_proposals": [proposal],
                "messages": [
                    ToolMessage(
                        content=f"Queued proposal to update event {event_id} ({pid}). Awaiting approval.",
                        tool_call_id=runtime.tool_call_id or "",
                    )
                ],
            }
        )

    def propose_delete_calendar_event(
        event_id: str,
        runtime: ToolRuntime,
        calendar_id: str = "primary",
    ) -> Command:
        """Queue deleting a calendar event that exists on Google Calendar (requires approval)."""
        eid = event_id.strip()
        existing, missing = _load_event(
            db, user_id, settings, event_id=eid, calendar_id=calendar_id
        )
        if missing or not existing:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=missing or "Unable to load existing event.",
                            tool_call_id=runtime.tool_call_id or "",
                        )
                    ]
                }
            )
        pid = str(uuid.uuid4())
        existing_fields = _event_to_proposal_fields(existing)
        proposal: dict = {
            "type": "delete_event",
            "id": pid,
            "event_id": eid,
            "calendar_id": calendar_id,
            "summary": existing_fields.get("summary"),
            "description": existing_fields.get("description"),
            "start_datetime": existing_fields.get("start_datetime"),
            "end_datetime": existing_fields.get("end_datetime"),
            "timezone": existing_fields.get("timezone"),
            "attendees": existing_fields.get("attendees"),
        }
        return Command(
            update={
                "pending_proposals": [proposal],
                "messages": [
                    ToolMessage(
                        content=f"Queued proposal to delete event {event_id} ({pid}). Awaiting approval.",
                        tool_call_id=runtime.tool_call_id or "",
                    )
                ],
            }
        )

    return [
        StructuredTool.from_function(
            propose_create_calendar_event,
            infer_schema=False,
            args_schema=args_schema_excluding_runtime(propose_create_calendar_event),
        ),
        StructuredTool.from_function(
            propose_update_calendar_event,
            infer_schema=False,
            args_schema=args_schema_excluding_runtime(propose_update_calendar_event),
        ),
        StructuredTool.from_function(
            propose_create_google_meet_meeting,
            infer_schema=False,
            args_schema=args_schema_excluding_runtime(propose_create_google_meet_meeting),
        ),
        StructuredTool.from_function(
            propose_delete_calendar_event,
            infer_schema=False,
            args_schema=args_schema_excluding_runtime(propose_delete_calendar_event),
        ),
    ]


def _validate_create_fields(
    *,
    summary: str,
    start_datetime: str,
    end_datetime: str,
    timezone: str,
    attendees: str,
) -> str | None:
    if not (summary or "").strip():
        return "Error: event title/summary is required."
    if not (start_datetime or "").strip():
        return "Error: start_datetime is required (RFC3339)."
    if not (end_datetime or "").strip():
        return "Error: end_datetime is required (RFC3339)."
    if not (timezone or "").strip():
        return "Error: timezone is required (IANA name, e.g. America/Los_Angeles)."
    if not (attendees or "").strip():
        return "Error: attendees is required — comma-separated participant email addresses."
    return None
