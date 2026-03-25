"""
Thin wrapper around Gmail API v1.

Creates drafts and sends mail using MIME messages; uses shared credential
refresh, HTTP timeouts, and retries on transient errors.
"""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.services.google_credentials import (
    build_gmail_service,
    ensure_fresh_credentials,
    google_api_call_with_retry,
)


def _encode_raw_message(to: str, subject: str, body: str, *, subtype: str = "plain") -> str:
    msg = MIMEText(body, _subtype=subtype, _charset="utf-8")
    msg["to"] = to
    msg["subject"] = subject
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


def create_email_draft(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    to: str,
    subject: str,
    body: str,
    body_subtype: str = "plain",
) -> dict[str, Any]:
    """Create a Gmail draft (compose scope)."""
    creds = ensure_fresh_credentials(db, user_id, settings)
    service = build_gmail_service(settings, creds)
    raw = _encode_raw_message(to, subject, body, subtype=body_subtype)
    draft_body: dict[str, Any] = {"message": {"raw": raw}}

    def _call() -> dict[str, Any]:
        return service.users().drafts().create(userId="me", body=draft_body).execute()

    return google_api_call_with_retry(_call, settings=settings)


def send_email(
    db: Session,
    user_id: int,
    settings: Settings,
    *,
    to: str,
    subject: str,
    body: str,
    body_subtype: str = "plain",
) -> dict[str, Any]:
    """Send a message (requires gmail.send scope)."""
    creds = ensure_fresh_credentials(db, user_id, settings)
    service = build_gmail_service(settings, creds)
    raw = _encode_raw_message(to, subject, body, subtype=body_subtype)
    send_body = {"raw": raw}

    def _call() -> dict[str, Any]:
        return service.users().messages().send(userId="me", body=send_body).execute()

    return google_api_call_with_retry(_call, settings=settings)
