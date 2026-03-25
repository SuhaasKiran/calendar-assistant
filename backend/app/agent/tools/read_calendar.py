"""Read-only calendar tools (safe without approval)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.tools import tool
from sqlalchemy.orm import Session

from app.agent.tools.common import format_tool_error, json_dumps
from app.config import Settings
from app.services import calendar_client


def check_window_conflicts_payload(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
    max_results: int = 50,
) -> tuple[bool | None, str]:
    """
    List events in ``[time_min, time_max)`` on the user's calendar.

    Returns ``(has_any_event, json_payload_or_error)``.
    If the API call fails, returns ``(None, error_message)`` — callers must not treat as
    "no conflicts".
    """
    try:
        raw = calendar_client.list_events(
            db,
            user_id,
            settings,
            time_min=time_min,
            time_max=time_max,
            calendar_id=calendar_id,
            max_results=max_results,
        )
    except Exception as e:
        return None, format_tool_error(e)
    items = raw.get("items") or []
    summaries = []
    for ev in items:
        summaries.append(
            {
                "id": ev.get("id"),
                "summary": ev.get("summary", "(no title)"),
                "start": ev.get("start"),
                "end": ev.get("end"),
            }
        )
    payload = json.dumps(
        {"count": len(summaries), "overlapping_events": summaries},
        indent=2,
    )
    return (len(summaries) > 0), payload


def _parse_event_bounds(ev: dict[str, Any]) -> tuple[datetime, datetime] | None:
    """Return (start, end) as timezone-aware UTC datetimes, or None if unparseable."""
    start = ev.get("start") or {}
    end = ev.get("end") or {}
    try:
        if "dateTime" in start and "dateTime" in end:
            s = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00"))
            e = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            return (s, e)
        if "date" in start and "date" in end:
            # All-day: date strings YYYY-MM-DD
            sd = datetime.fromisoformat(start["date"]).replace(tzinfo=timezone.utc)
            ed = datetime.fromisoformat(end["date"]).replace(tzinfo=timezone.utc)
            # Google uses exclusive end date for all-day
            return (sd, ed)
    except (ValueError, TypeError, KeyError):
        pass
    return None


def build_read_calendar_tools(
    db: Session,
    user_id: int,
    settings: Settings,
) -> list:
    """List/get events and deterministic busy-time analytics."""

    @tool
    def list_calendar_events(
        time_min: str,
        time_max: str,
        calendar_id: str = "primary",
        max_results: int = 50,
    ) -> str:
        """List calendar events with time_min (inclusive) and time_max (exclusive), both RFC3339."""
        try:
            out = calendar_client.list_events(
                db,
                user_id,
                settings,
                time_min=time_min,
                time_max=time_max,
                calendar_id=calendar_id,
                max_results=max_results,
            )
            return json_dumps(out)
        except Exception as e:
            return format_tool_error(e)

    @tool
    def get_calendar_event(event_id: str, calendar_id: str = "primary") -> str:
        """Fetch one calendar event by id."""
        try:
            out = calendar_client.get_event(
                db, user_id, settings, event_id=event_id, calendar_id=calendar_id
            )
            return json_dumps(out)
        except Exception as e:
            return format_tool_error(e)

    @tool
    def summarize_calendar_busy_time(
        time_min: str,
        time_max: str,
        calendar_id: str = "primary",
        max_results: int = 250,
    ) -> str:
        """
        Compute how much time is spent in scheduled events between two RFC3339 bounds.
        Returns JSON: total_events, total_busy_seconds, total_busy_hours, busy_ratio_of_range (if range parseable),
        and per-event summary (summary/title and duration minutes). Use for questions like
        'how much time in meetings' or 'meeting load'.
        """
        try:
            raw = calendar_client.list_events(
                db,
                user_id,
                settings,
                time_min=time_min,
                time_max=time_max,
                calendar_id=calendar_id,
                max_results=max_results,
            )
            items = raw.get("items") or []
            range_start = datetime.fromisoformat(time_min.replace("Z", "+00:00"))
            range_end = datetime.fromisoformat(time_max.replace("Z", "+00:00"))
            if range_start.tzinfo is None:
                range_start = range_start.replace(tzinfo=timezone.utc)
            if range_end.tzinfo is None:
                range_end = range_end.replace(tzinfo=timezone.utc)
            total_seconds = 0.0
            breakdown: list[dict[str, Any]] = []
            for ev in items:
                bounds = _parse_event_bounds(ev)
                if bounds is None:
                    continue
                s, e = bounds
                # Clip to query window
                clip_start = max(s, range_start)
                clip_end = min(e, range_end)
                if clip_end <= clip_start:
                    dur = 0.0
                else:
                    dur = (clip_end - clip_start).total_seconds()
                total_seconds += dur
                breakdown.append(
                    {
                        "summary": ev.get("summary", "(no title)"),
                        "id": ev.get("id"),
                        "duration_minutes": round(dur / 60.0, 2) if dur else 0.0,
                    }
                )
            range_seconds = max(0.0, (range_end - range_start).total_seconds())
            ratio = (total_seconds / range_seconds) if range_seconds > 0 else None
            payload = {
                "total_events": len(items),
                "total_busy_seconds": round(total_seconds, 2),
                "total_busy_hours": round(total_seconds / 3600.0, 4),
                "range_seconds": range_seconds,
                "busy_ratio_of_range": round(ratio, 4) if ratio is not None else None,
                "breakdown": breakdown,
            }
            return json.dumps(payload, indent=2)
        except Exception as e:
            return format_tool_error(e)

    @tool
    def check_calendar_time_conflicts(
        time_min: str,
        time_max: str,
        calendar_id: str = "primary",
    ) -> str:
        """Check the user's calendar for events in [time_min, time_max) (RFC3339). Call before proposing a new event."""
        _has, payload = check_window_conflicts_payload(
            db,
            user_id,
            settings,
            time_min=time_min,
            time_max=time_max,
            calendar_id=calendar_id,
        )
        return payload  # includes overlap list or API error message

    return [
        list_calendar_events,
        get_calendar_event,
        summarize_calendar_busy_time,
        check_calendar_time_conflicts,
    ]
