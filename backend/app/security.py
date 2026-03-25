from datetime import datetime, timedelta, timezone

import jwt

JWT_ALGORITHM = "HS256"


def create_session_token(user_id: int, secret: str, expires_in_seconds: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str, secret: str) -> int:
    payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    sub = payload.get("sub")
    if sub is None:
        raise jwt.InvalidTokenError("missing sub")
    return int(sub)
