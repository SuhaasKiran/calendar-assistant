from __future__ import annotations

import os
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.config import Settings

# Allow Google to return a broader scope than what was requested (happens when the user
# previously granted additional scopes and `include_granted_scopes` merges them).
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

GOOGLE_SCOPES: list[str] = [
    # Identity — needed for fetch_google_user_profile (oauth2 v2 userinfo)
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    # Calendar
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
    # Gmail
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
    # Drive (metadata only)
    # "https://www.googleapis.com/auth/drive.readonly",
    # "https://www.googleapis.com/auth/drive.metadata.readonly",
]


def _client_config(settings: Settings) -> dict:
    if not settings.google_client_id or not settings.google_client_secret:
        raise RuntimeError("Google OAuth client id/secret are not configured")
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.google_redirect_uri],
        }
    }


def build_flow(settings: Settings) -> Flow:
    # PKCE is auto-generated in `authorization_url()` on this Flow instance. The callback
    # uses a *new* Flow, so it would not have the same `code_verifier` → token exchange
    # fails. For a confidential web client (client secret), PKCE is optional; disable it.
    return Flow.from_client_config(
        _client_config(settings),
        scopes=GOOGLE_SCOPES,
        redirect_uri=settings.google_redirect_uri,
        autogenerate_code_verifier=False,
    )


def authorization_url(flow: Flow) -> tuple[str, str]:
    url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    return url, state


def exchange_code_for_credentials(flow: Flow, code: str) -> Credentials:
    """Exchange the auth code for tokens.

    Use `code=` (not `authorization_response=`) so oauthlib does not parse an
    `http://localhost` callback URL, which triggers InsecureTransportError in dev.
    State is already verified in the route via cookie + query param.
    """
    flow.fetch_token(code=code)
    return flow.credentials


def credentials_expiry_utc(creds: Credentials) -> datetime | None:
    if creds.expiry is None:
        return None
    exp = creds.expiry
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp


def fetch_google_user_profile(creds: Credentials) -> tuple[str, str | None]:
    """Return (google_sub, email) from Google's userinfo API."""
    service = build("oauth2", "v2", credentials=creds, cache_discovery=False)
    info = service.userinfo().get().execute()
    sub = str(info.get("id") or info.get("sub") or "")
    if not sub:
        raise RuntimeError("Google userinfo did not return a user id")
    email = info.get("email")
    return sub, email if isinstance(email, str) else None
