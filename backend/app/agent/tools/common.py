from __future__ import annotations

import json
from typing import Any

from googleapiclient.errors import HttpError

from app.services.google_credentials import ReauthRequiredError


def json_dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def format_tool_error(exc: Exception) -> str:
    if isinstance(exc, ReauthRequiredError):
        return f"Error: {exc}"
    if isinstance(exc, HttpError):
        try:
            raw = exc.content
            err_content = raw.decode("utf-8", errors="replace") if raw else ""
        except Exception:
            err_content = str(exc)
        return f"Google API error ({exc.resp.status}): {err_content}"
    return f"Error: {exc}"
