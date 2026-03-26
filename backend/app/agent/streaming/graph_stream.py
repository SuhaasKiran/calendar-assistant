"""
Stream LangGraph outputs as JSON lines for SSE (interrupts + final assistant text).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from typing import Any
from langgraph.types import Command

from langchain_core.messages import AIMessage
from app.core.request_context import get_request_id

logger = logging.getLogger(__name__)
GENERIC_STREAM_ERROR_MESSAGE = "Something went wrong on our side. Please try again."


def _last_assistant_reply(messages: list[Any]) -> str:
    for m in reversed(messages or []):
        if isinstance(m, AIMessage) and m.content:
            if m.tool_calls:
                continue
            c = m.content
            return c if isinstance(c, str) else str(c)
    return ""


def stream_graph_sse(
    graph: Any,
    *,
    input: dict[str, Any] | Command,
    config: dict[str, Any],
) -> Iterator[str]:
    """
    Yield newline-delimited JSON for SSE: `interrupt` when paused, then `content`
    with the latest assistant reply when the turn completes without interrupt.
    """
    interrupted = False
    try:
        for _mode, chunk in graph.stream(
            input,
            config,
            stream_mode=["updates"],
        ):
            if not isinstance(chunk, dict) or "__interrupt__" not in chunk:
                continue
            interrupted = True
            payload = [
                {"id": i.id, "value": i.value} for i in chunk["__interrupt__"]
            ]
            yield json.dumps({"type": "interrupt", "interrupts": payload}) + "\n"

        if interrupted:
            # Interrupted turns are paused and awaiting a resume payload.
            # Do not emit "done" because UI treats it as terminal completion.
            return

        snap = graph.get_state(config)
        vals = snap.values if snap else None
        msgs = (vals or {}).get("messages") or []
        text = _last_assistant_reply(list(msgs))
        if text:
            yield json.dumps({"type": "content", "text": text}) + "\n"

        yield json.dumps({"type": "done"}) + "\n"
    except Exception:
        logger.exception("Failed while streaming graph SSE response")
        yield (
            json.dumps(
                {
                    "type": "error",
                    "message": GENERIC_STREAM_ERROR_MESSAGE,
                    "code": "STREAM_FAILURE",
                    "request_id": get_request_id(),
                    "retryable": True,
                }
            )
            + "\n"
        )
