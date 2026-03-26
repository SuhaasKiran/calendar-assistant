"""
Build and refresh Google API credentials for a logged-in user.

Loads tokens from `OAuthToken`, refreshes when expired, persists new access
token + expiry. On `invalid_grant`, raises `ReauthRequiredError`.

Shared by `calendar_client`, `gmail_client`, and agent tools.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TypeVar

import httplib2
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_httplib2 import AuthorizedHttp
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.resilience import call_with_retry
from app.db.models import OAuthToken
from app.services.google_oauth import GOOGLE_SCOPES, credentials_expiry_utc

T = TypeVar("T")
logger = logging.getLogger(__name__)


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
    """Plain httplib2 client with a fixed timeout (for use inside AuthorizedHttp)."""
    return httplib2.Http(timeout=settings.google_http_timeout_seconds)


def _authorized_http(settings: Settings, creds: Credentials) -> AuthorizedHttp:
    """
    Credentials + timeout on one HTTP stack.

    ``googleapiclient.discovery.build`` accepts either ``credentials`` *or* ``http``,
    not both; ``AuthorizedHttp`` attaches OAuth to an underlying ``httplib2.Http``.
    """
    return AuthorizedHttp(creds, http=build_authorized_http(settings))


def build_calendar_service(settings: Settings, creds: Credentials):
    return build(
        "calendar",
        "v3",
        http=_authorized_http(settings, creds),
        cache_discovery=False,
    )


def build_gmail_service(settings: Settings, creds: Credentials):
    return build(
        "gmail",
        "v1",
        http=_authorized_http(settings, creds),
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
    if not settings.reliability_features_enabled:
        return fn()

    def _is_retryable(exc: Exception) -> bool:
        if not isinstance(exc, HttpError):
            return False
        status = exc.resp.status
        return status in (429, 500, 502, 503, 504)

    attempts = 0

    def _wrapped() -> T:
        nonlocal attempts
        attempts += 1
        return fn()

    try:
        out = call_with_retry(
            _wrapped,
            max_attempts=max(1, settings.google_api_max_retries),
            base_delay_seconds=settings.google_api_retry_base_delay_seconds,
            max_delay_seconds=settings.google_api_retry_max_delay_seconds,
            is_retryable_error=_is_retryable,
        )
        if attempts > 1:
            logger.warning("google_api_recovered_after_retries attempts=%s", attempts)
        return out
    except Exception:
        logger.exception("google_api_call_failed attempts=%s", attempts)
        raise
