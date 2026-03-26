"""Shared assistant identity loaded from frontend/public configuration."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_ASSISTANT_NAME = "Assistant"
ASSISTANT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "frontend" / "public" / "assistant-config.json"
)


@lru_cache(maxsize=1)
def get_assistant_name() -> str:
    """Return assistant display name from shared config, with safe fallback."""
    try:
        raw = ASSISTANT_CONFIG_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return DEFAULT_ASSISTANT_NAME

    name = data.get("assistantName") if isinstance(data, dict) else None
    if isinstance(name, str):
        stripped = name.strip()
        if stripped:
            return stripped
    return DEFAULT_ASSISTANT_NAME
