import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db.models import OAuthToken, User
from app.db.session import get_db
from app.deps import get_current_user
from app.schemas.auth import UserOut
from app.security import create_session_token
from app.services.google_oauth import (
    authorization_url,
    build_flow,
    credentials_expiry_utc,
    exchange_code_for_credentials,
    fetch_google_user_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _post_login_redirect(settings: Settings, query: dict[str, str]) -> RedirectResponse:
    base = settings.oauth_post_login_redirect.rstrip("/")
    url = f"{base}?{urlencode(query)}"
    return RedirectResponse(url=url, status_code=302)


@router.get("/google/start")
def google_oauth_start(
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    if not settings.google_client_id or not settings.google_client_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )
    if not settings.secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SECRET_KEY is not set",
        )
    flow = build_flow(settings)
    url, state = authorization_url(flow)
    response = RedirectResponse(url=url, status_code=302)
    response.set_cookie(
        key=settings.oauth_state_cookie_name,
        value=state,
        max_age=settings.oauth_state_max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.get("/google/callback")
def google_oauth_callback(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    if error:
        return _post_login_redirect(settings, {"error": error})
    if not settings.secret_key:
        return _post_login_redirect(settings, {"error": "server_not_configured"})
    if not code or not state:
        return _post_login_redirect(settings, {"error": "missing_code"})

    cookie_state = request.cookies.get(settings.oauth_state_cookie_name)
    if not cookie_state or cookie_state != state:
        return _post_login_redirect(settings, {"error": "invalid_state"})

    flow = build_flow(settings)
    try:
        creds = exchange_code_for_credentials(flow, code)
    except Exception:
        logger.exception("Google OAuth token exchange failed")
        return _post_login_redirect(settings, {"error": "token_exchange_failed"})

    try:
        google_sub, email = fetch_google_user_profile(creds)
    except Exception:
        logger.exception("Google userinfo fetch failed")
        return _post_login_redirect(settings, {"error": "userinfo_failed"})

    user = db.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        user = User(google_sub=google_sub, email=email)
        db.add(user)
        db.flush()
    elif email:
        user.email = email

    oauth_token = db.scalar(select(OAuthToken).where(OAuthToken.user_id == user.id))
    if oauth_token is None:
        oauth_token = OAuthToken(user_id=user.id)
        db.add(oauth_token)

    if creds.refresh_token:
        oauth_token.refresh_token = creds.refresh_token
    oauth_token.access_token = creds.token
    oauth_token.access_token_expires_at = credentials_expiry_utc(creds)

    db.commit()

    session_jwt = create_session_token(
        user.id,
        settings.secret_key,
        settings.session_cookie_max_age_seconds,
    )

    response = _post_login_redirect(settings, {"login": "ok"})
    response.delete_cookie(settings.oauth_state_cookie_name, path="/")
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_jwt,
        max_age=settings.session_cookie_max_age_seconds,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
def logout(settings: Settings = Depends(get_settings)) -> Response:
    r = Response(status_code=status.HTTP_204_NO_CONTENT)
    r.delete_cookie(settings.session_cookie_name, path="/")
    return r


@router.get("/me", response_model=UserOut)
def auth_me(user: User = Depends(get_current_user)) -> User:
    return user
