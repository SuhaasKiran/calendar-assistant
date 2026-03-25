"""
Apply LangSmith / LangChain tracing env vars from Settings.

LangChain reads ``LANGCHAIN_*`` from the process environment when runs execute.
Pydantic loads ``.env`` into ``Settings``; we mirror those values into ``os.environ``
at startup so tracing works even when variables are only in ``.env``.
"""

from __future__ import annotations

import os

from app.config import Settings


def configure_langsmith_from_settings(settings: Settings) -> None:
    if settings.langchain_tracing_v2:
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        if settings.langchain_api_key:
            os.environ["LANGCHAIN_API_KEY"] = settings.langchain_api_key
        if settings.langchain_project:
            os.environ["LANGCHAIN_PROJECT"] = settings.langchain_project
        if settings.langchain_endpoint:
            os.environ["LANGCHAIN_ENDPOINT"] = settings.langchain_endpoint.rstrip("/")
    else:
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
