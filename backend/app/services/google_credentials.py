"""
Build and refresh Google API credentials for a logged-in user.

Loads tokens from `OAuthToken`, refreshes when expired, persists new access
token + expiry. On `invalid_grant`, raises `ReauthRequiredError`.

Shared by `calendar_client`, `gmail_client`, and agent tools.
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

import httplib2
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import OAuthToken
from app.services.google_oauth import GOOGLE_SCOPES, credentials_expiry_utc

T = TypeVar("T")


class ReauthRequiredError(Exception):
    """Raised when the stored refresh token is missing or Google rejected refresh (e.g. invalid_grant)."""


def ensure_fresh_credentials(
    db: Session,
    user_id: int,
    settings: Settings,
) -> Credentials:
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError("Google OAuth client id/secret are not configured")

    oauth_token = db.scalar(select(OAuthToken).where(OAuthToken.user_id == user_id))
    if oauth_token is None:
        raise ReauthRequiredError("No OAuth tokens for this user; sign in with Google first.")
    if not oauth_token.refresh_token:
        raise ReauthRequiredError("No refresh token stored; sign in again (offline access).")

    creds = Credentials(
        token=oauth_token.access_token,
        refresh_token=oauth_token.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=GOOGLE_SCOPES,
        expiry=oauth_token.access_token_expires_at,
    )

    if creds.token is None or creds.expired:
        try:
            creds.refresh(Request())
        except RefreshError as e:
            raise ReauthRequiredError(
                "Google session expired; please sign in again."
            ) from e
        oauth_token.access_token = creds.token
        oauth_token.access_token_expires_at = credentials_expiry_utc(creds)
        db.commit()

    return creds


def build_authorized_http(settings: Settings) -> httplib2.Http:
    """HTTP client with a fixed timeout for all Google REST calls."""
    return httplib2.Http(timeout=settings.google_http_timeout_seconds)


def build_calendar_service(settings: Settings, creds: Credentials):
    return build(
        "calendar",
        "v3",
        credentials=creds,
        http=build_authorized_http(settings),
        cache_discovery=False,
    )


def build_gmail_service(settings: Settings, creds: Credentials):
    return build(
        "gmail",
        "v1",
        credentials=creds,
        http=build_authorized_http(settings),
        cache_discovery=False,
    )


def google_api_call_with_retry(
    fn: Callable[[], T],
    *,
    settings: Settings,
) -> T:
    """
    Run a synchronous Google API callable with retries on transient errors.

    Retries HTTP 429 and 5xx from HttpError, with exponential backoff.
    """
    max_attempts = max(1, settings.google_api_max_retries)
    base = settings.google_api_retry_base_delay_seconds
    for attempt in range(max_attempts):
        try:
            return fn()
        except HttpError as e:
            status = e.resp.status
            retryable = status in (429, 500, 502, 503, 504)
            if not retryable or attempt == max_attempts - 1:
                raise
            delay = base * (2**attempt) + random.uniform(0, 0.1)
            time.sleep(delay)
