"""
Execute approved calendar/email proposals using existing Google API clients.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.orm import Session

from googleapiclient.errors import HttpError

from app.config import Settings
from app.services import calendar_client, gmail_client
from app.services.google_credentials import ReauthRequiredError


def _meet_conference_payload(seed: str) -> dict[str, Any]:
    return {
        "createRequest": {
            "conferenceSolutionKey": {"type": "hangoutsMeet"},
            "requestId": seed,
        }
    }


def _parse_attendees(raw: Any) -> list[dict[str, str]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [{"email": str(x).strip()} for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []
    parts = [p.strip() for p in s.replace(";", ",").split(",") if p.strip()]
    return [{"email": p} for p in parts]


def _http_err(e: HttpError) -> str:
    try:
        raw = e.content
        body = raw.decode("utf-8", errors="replace") if raw else ""
    except Exception:
        body = str(e)
    return f"Google API error ({e.resp.status}): {body}"


def execute_proposal(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    default_timezone: str,
    proposal: dict[str, Any],
) -> dict[str, Any]:
    """
    Run a single proposal. Returns { "ok": bool, "proposal_id", "detail": str, "result": any }.
    """
    pid = proposal.get("id", str(uuid.uuid4()))
    ptype = proposal.get("type")

    try:
        if ptype == "create_event":
            request_id = str(proposal.get("id") or uuid.uuid4())
            body: dict[str, Any] = {
                "summary": proposal["summary"],
                "start": {
                    "dateTime": proposal["start_datetime"],
                    "timeZone": proposal["timezone"],
                },
                "end": {
                    "dateTime": proposal["end_datetime"],
                    "timeZone": proposal["timezone"],
                },
                # Default behavior: every created event should include a Meet link.
                "conferenceData": _meet_conference_payload(request_id),
            }
            if proposal.get("description"):
                body["description"] = proposal["description"]
            atts = _parse_attendees(proposal.get("attendees"))
            if atts:
                body["attendees"] = atts
            out = calendar_client.create_event(
                db,
                user_id,
                settings,
                body=body,
                calendar_id=proposal.get("calendar_id") or "primary",
                conference_data_version=1,
            )
            return {"ok": True, "proposal_id": pid, "detail": "Event created", "result": out}

        if ptype == "update_event":
            cal_id = proposal.get("calendar_id") or "primary"
            eid = proposal["event_id"]
            current = calendar_client.get_event(
                db, user_id, settings, event_id=eid, calendar_id=cal_id
            )
            if proposal.get("summary") is not None:
                current["summary"] = proposal["summary"]
            if proposal.get("description") is not None:
                current["description"] = proposal["description"]
            if proposal.get("start_datetime") and proposal.get("end_datetime"):
                tz = proposal.get("timezone") or default_timezone
                current["start"] = {
                    "dateTime": proposal["start_datetime"],
                    "timeZone": tz,
                }
                current["end"] = {
                    "dateTime": proposal["end_datetime"],
                    "timeZone": tz,
                }
            if proposal.get("attendees") is not None:
                current["attendees"] = _parse_attendees(proposal.get("attendees"))
            out = calendar_client.update_event(
                db,
                user_id,
                settings,
                event_id=eid,
                body=current,
                calendar_id=cal_id,
            )
            return {"ok": True, "proposal_id": pid, "detail": "Event updated", "result": out}

        if ptype == "delete_event":
            calendar_client.delete_event(
                db,
                user_id,
                settings,
                event_id=proposal["event_id"],
                calendar_id=proposal.get("calendar_id") or "primary",
            )
            return {
                "ok": True,
                "proposal_id": pid,
                "detail": "Event deleted",
                "result": {"deleted_event_id": proposal["event_id"]},
            }

        if ptype == "create_email_draft":
            out = gmail_client.create_email_draft(
                db,
                user_id,
                settings,
                to=proposal["to"],
                subject=proposal["subject"],
                body=proposal["body"],
            )
            return {"ok": True, "proposal_id": pid, "detail": "Draft created", "result": out}

        if ptype == "send_email":
            out = gmail_client.send_email(
                db,
                user_id,
                settings,
                to=proposal["to"],
                subject=proposal["subject"],
                body=proposal["body"],
            )
            return {"ok": True, "proposal_id": pid, "detail": "Email sent", "result": out}

        return {
            "ok": False,
            "proposal_id": pid,
            "detail": f"Unknown proposal type: {ptype}",
            "result": None,
        }
    except ReauthRequiredError as e:
        return {"ok": False, "proposal_id": pid, "detail": str(e), "result": None}
    except HttpError as e:
        return {"ok": False, "proposal_id": pid, "detail": _http_err(e), "result": None}
    except Exception as e:
        return {"ok": False, "proposal_id": pid, "detail": str(e), "result": None}


def execute_all_proposals(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    default_timezone: str,
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Execute proposals in order; each outcome is independent (partial success)."""
    return [
        execute_proposal(
            db,
            user_id,
            settings,
            default_timezone=default_timezone,
            proposal=p,
        )
        for p in proposals
    ]


def format_execution_summary(results: list[dict[str, Any]]) -> str:
    lines = []
    for r in results:
        status = "ok" if r.get("ok") else "failed"
        lines.append(f"- [{status}] {r.get('proposal_id')}: {r.get('detail')}")
    return "\n".join(lines) if lines else "No actions executed."
