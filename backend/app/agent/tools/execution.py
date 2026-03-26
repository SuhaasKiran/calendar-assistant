"""
Execute approved calendar/email proposals using existing Google API clients.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from googleapiclient.errors import HttpError

from app.config import Settings
from app.services import calendar_client, gmail_client
from app.services.google_credentials import ReauthRequiredError

logger = logging.getLogger(__name__)


def _result_success(
    *,
    pid: str,
    ptype: str | None,
    detail: str,
    result: Any,
    external_reference: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "status": "succeeded",
        "error_code": None,
        "retryable": False,
        "external_reference": external_reference,
        "proposal_id": pid,
        "type": ptype,
        "detail": detail,
        "result": result,
    }


def _result_failure(
    *,
    pid: str,
    ptype: str | None,
    detail: str,
    error_code: str,
    retryable: bool,
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "failed",
        "error_code": error_code,
        "retryable": retryable,
        "external_reference": None,
        "proposal_id": pid,
        "type": ptype,
        "detail": detail,
        "result": None,
    }


def _require_fields(payload: dict[str, Any], fields: list[str], *, action: str) -> None:
    missing = [f for f in fields if not payload.get(f)]
    if missing:
        raise ValueError(f"{action} response missing fields: {', '.join(missing)}")


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
            _require_fields(out, ["id"], action="create_event")
            return _result_success(
                pid=pid,
                ptype=ptype,
                detail="Event created",
                result=out,
                external_reference=str(out.get("id")),
            )

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
            _require_fields(out, ["id"], action="update_event")
            return _result_success(
                pid=pid,
                ptype=ptype,
                detail="Event updated",
                result=out,
                external_reference=str(out.get("id")),
            )

        if ptype == "delete_event":
            cal_id = proposal.get("calendar_id") or "primary"
            existing = calendar_client.get_event(
                db,
                user_id,
                settings,
                event_id=proposal["event_id"],
                calendar_id=cal_id,
            )
            calendar_client.delete_event(
                db,
                user_id,
                settings,
                event_id=proposal["event_id"],
                calendar_id=cal_id,
            )
            return _result_success(
                pid=pid,
                ptype=ptype,
                detail="Event deleted",
                result=existing,
                external_reference=str(existing.get("id") or proposal.get("event_id")),
            )

        if ptype == "create_email_draft":
            out = gmail_client.create_email_draft(
                db,
                user_id,
                settings,
                to=proposal["to"],
                subject=proposal["subject"],
                body=proposal["body"],
            )
            draft_obj = out.get("draft") if isinstance(out, dict) else None
            if not isinstance(draft_obj, dict):
                raise ValueError("create_email_draft response missing draft object")
            _require_fields(draft_obj, ["id"], action="create_email_draft")
            return {
                **_result_success(
                    pid=pid,
                    ptype=ptype,
                    detail="Draft created",
                    result=out,
                    external_reference=str(draft_obj.get("id")),
                ),
                "to": proposal.get("to"),
                "subject": proposal.get("subject"),
            }

        if ptype == "send_email":
            out = gmail_client.send_email(
                db,
                user_id,
                settings,
                to=proposal["to"],
                subject=proposal["subject"],
                body=proposal["body"],
            )
            _require_fields(out, ["id"], action="send_email")
            return {
                **_result_success(
                    pid=pid,
                    ptype=ptype,
                    detail="Email sent",
                    result=out,
                    external_reference=str(out.get("id")),
                ),
                "to": proposal.get("to"),
                "subject": proposal.get("subject"),
            }

        return _result_failure(
            pid=pid,
            ptype=ptype,
            detail=f"Unknown proposal type: {ptype}",
            error_code="UNKNOWN_PROPOSAL_TYPE",
            retryable=False,
        )
    except ReauthRequiredError as e:
        return _result_failure(
            pid=pid,
            ptype=ptype,
            detail=str(e),
            error_code="REAUTH_REQUIRED",
            retryable=False,
        )
    except HttpError as e:
        retryable = e.resp.status in (429, 500, 502, 503, 504)
        return _result_failure(
            pid=pid,
            ptype=ptype,
            detail=_http_err(e),
            error_code=f"GOOGLE_HTTP_{e.resp.status}",
            retryable=retryable,
        )
    except Exception as e:
        logger.exception("Unexpected proposal execution failure proposal_id=%s type=%s", pid, ptype)
        return _result_failure(
            pid=pid,
            ptype=ptype,
            detail=str(e),
            error_code="EXECUTION_EXCEPTION",
            retryable=False,
        )


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


def _event_dt(ev: dict[str, Any], key: str) -> str:
    node = ev.get(key) or {}
    if not isinstance(node, dict):
        return "—"
    dt = node.get("dateTime") or node.get("date")
    tz = node.get("timeZone")
    if not dt:
        return "—"
    return f"{dt} ({tz})" if tz else str(dt)


def _event_participants(ev: dict[str, Any]) -> str:
    atts = ev.get("attendees")
    if not isinstance(atts, list):
        return "—"
    emails = [str(a.get("email")).strip() for a in atts if isinstance(a, dict) and a.get("email")]
    return ", ".join(emails) if emails else "—"


def _event_meeting_link(ev: dict[str, Any]) -> str:
    if ev.get("hangoutLink"):
        return str(ev["hangoutLink"])
    conf = ev.get("conferenceData") or {}
    if isinstance(conf, dict):
        entries = conf.get("entryPoints") or []
        if isinstance(entries, list):
            for ep in entries:
                if isinstance(ep, dict) and ep.get("entryPointType") == "video" and ep.get("uri"):
                    return str(ep["uri"])
    return "—"


def _event_page_link(ev: dict[str, Any]) -> str:
    raw = ev.get("htmlLink")
    if not isinstance(raw, str):
        return "—"
    link = raw.strip()
    if not link:
        return "—"
    return f"[Open calendar event]({link})"


def _format_call_details(title: str, ev: dict[str, Any]) -> str:
    return (
        f"{title}\n"
        f"Title: {ev.get('summary') or '—'}\n"
        f"Summary: {ev.get('description') or '—'}\n"
        f"Start: {_event_dt(ev, 'start')}\n"
        f"End: {_event_dt(ev, 'end')}\n"
        f"Participants: {_event_participants(ev)}\n"
        f"Event: {_event_page_link(ev)}\n"
        f"Meeting link: {_event_meeting_link(ev)}"
    )


def _format_sent_email_details(r: dict[str, Any]) -> str:
    out = r.get("result")
    result = out if isinstance(out, dict) else {}
    to = str(r.get("to") or "—")
    subject = str(r.get("subject") or "—")
    message_id = str(result.get("id") or "—")
    thread_id = str(result.get("threadId") or "—")
    return (
        "Email sent successfully.\n"
        f"To: {to}\n"
        f"Subject: {subject}\n"
        # f"Message ID: {message_id}\n"
        # f"Thread ID: {thread_id}"
    )


def format_execution_summary(results: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for r in results:
        action = r.get("type")
        if not r.get("ok"):
            retry_hint = " You can retry this action." if r.get("retryable") else ""
            blocks.append(f"Could not complete action: {r.get('detail')}.{retry_hint}".strip())
            continue

        result = r.get("result")
        if action == "create_event" and isinstance(result, dict):
            blocks.append(_format_call_details("Call scheduled successfully.", result))
            continue
        if action == "update_event" and isinstance(result, dict):
            blocks.append(_format_call_details("Call updated successfully.", result))
            continue
        if action == "delete_event" and isinstance(result, dict):
            blocks.append(_format_call_details("Call cancelled successfully.", result))
            continue
        if action == "create_email_draft":
            to = str(r.get("to") or "—")
            subject = str(r.get("subject") or "—")
            blocks.append(f"Email draft created.\nTo: {to}\nSubject: {subject}")
            continue
        if action == "send_email":
            blocks.append(_format_sent_email_details(r))
            continue

        ref = r.get("external_reference")
        if ref:
            blocks.append(f"{str(r.get('detail') or 'Action completed.')}\nReference: {ref}")
        else:
            blocks.append(str(r.get("detail") or "Action completed."))
    return "\n\n".join(blocks)
