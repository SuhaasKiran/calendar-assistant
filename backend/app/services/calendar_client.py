"""
Thin wrapper around Google Calendar API v3.

Uses shared credential refresh, HTTP timeouts, and retries on transient errors.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.services.google_credentials import (
    build_calendar_service,
    ensure_fresh_credentials,
    google_api_call_with_retry,
)


def get_event(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    event_id: str,
    calendar_id: str = "primary",
) -> dict[str, Any]:
    """Fetch a single event by id."""
    creds = ensure_fresh_credentials(db, user_id, settings)
    service = build_calendar_service(settings, creds)

    def _call() -> dict[str, Any]:
        return service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    return google_api_call_with_retry(_call, settings=settings)


def list_events(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    time_min: str,
    time_max: str,
    calendar_id: str = "primary",
    max_results: int = 50,
    single_events: bool = True,
    order_by: str = "startTime",
) -> dict[str, Any]:
    """
    List events in [time_min, time_max). `time_min` / `time_max` are RFC3339 strings
    (e.g. from ISO 8601 datetimes in the user's timezone).
    """
    creds = ensure_fresh_credentials(db, user_id, settings)
    service = build_calendar_service(settings, creds)

    def _call() -> dict[str, Any]:
        return (
            service.events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                maxResults=max_results,
                singleEvents=single_events,
                orderBy=order_by,
            )
            .execute()
        )

    return google_api_call_with_retry(_call, settings=settings)


def create_event(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    body: dict[str, Any],
    calendar_id: str = "primary",
    conference_data_version: int | None = None,
) -> dict[str, Any]:
    """Create an event; `body` matches Calendar API Event resource."""
    creds = ensure_fresh_credentials(db, user_id, settings)
    service = build_calendar_service(settings, creds)

    def _call() -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "calendarId": calendar_id,
            "body": body,
        }
        if conference_data_version is not None:
            kwargs["conferenceDataVersion"] = conference_data_version
        return service.events().insert(**kwargs).execute()

    return google_api_call_with_retry(_call, settings=settings)


def update_event(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    event_id: str,
    body: dict[str, Any],
    calendar_id: str = "primary",
) -> dict[str, Any]:
    creds = ensure_fresh_credentials(db, user_id, settings)
    service = build_calendar_service(settings, creds)

    def _call() -> dict[str, Any]:
        return (
            service.events()
            .update(calendarId=calendar_id, eventId=event_id, body=body)
            .execute()
        )

    return google_api_call_with_retry(_call, settings=settings)


def delete_event(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    event_id: str,
    calendar_id: str = "primary",
) -> None:
    creds = ensure_fresh_credentials(db, user_id, settings)
    service = build_calendar_service(settings, creds)

    def _call() -> None:
        service.events().delete(calendarId=calendar_id, eventId=event_id).execute()

    google_api_call_with_retry(_call, settings=settings)
