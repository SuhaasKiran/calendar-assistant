"""
Bridge LangGraph / LangChain agent runs to SSE-friendly chunks.

Yields small dicts the HTTP layer can JSON-serialize into `data:` lines.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessageChunk
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)
GENERIC_STREAM_ERROR_MESSAGE = "Something went wrong on our side. Please try again."


def _chunk_text(chunk: AIMessageChunk) -> str:
    c = chunk.content
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
        return "".join(parts)
    return ""


async def stream_agent_events(
    graph: Any,
    *,
    messages: list,
    run_config: RunnableConfig | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """
    Stream model tokens and tool lifecycle events from `graph.astream_events`.

    Events yielded (all JSON-serializable dicts):
    - `{"type": "content", "text": "..."}` — LLM token / chunk text
    - `{"type": "tool_start", "name": str, "input": any}` — tool invocation
    - `{"type": "tool_end", "name": str, "output": str}` — tool result
    - `{"type": "tool_error", "name": str, "message": str}` — tool failure
    - `{"type": "error", "message": str}` — unrecoverable failure
    - `{"type": "done"}` — run finished successfully
    """
    cfg: RunnableConfig = run_config or {}
    try:
        async for event in graph.astream_events(
            {"messages": messages},
            config=cfg,
            version="v2",
        ):
            kind = event.get("event")
            data = event.get("data") or {}
            name = event.get("name")

            if kind == "on_chat_model_stream":
                chunk = data.get("chunk")
                if isinstance(chunk, AIMessageChunk):
                    text = _chunk_text(chunk)
                    if text:
                        yield {"type": "content", "text": text}

            elif kind == "on_tool_start" and name:
                yield {"type": "tool_start", "name": name, "input": data.get("input")}

            elif kind == "on_tool_end" and name:
                out = data.get("output")
                out_str = out if isinstance(out, str) else str(out)
                yield {"type": "tool_end", "name": name, "output": out_str}

            elif kind == "on_tool_error" and name:
                err = data.get("error")
                yield {"type": "tool_error", "name": name, "message": str(err)}

        yield {"type": "done"}
    except Exception:
        logger.exception("Failed while streaming agent events")
        yield {"type": "error", "message": GENERIC_STREAM_ERROR_MESSAGE}
