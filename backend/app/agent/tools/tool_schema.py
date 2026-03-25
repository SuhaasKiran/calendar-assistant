"""Helpers for LangChain tools that take an injected ``runtime: ToolRuntime``."""

from collections.abc import Callable

from langchain_core.tools import create_schema_from_function
from langchain_core.tools.structured import _filter_schema_args


def args_schema_excluding_runtime(func: Callable) -> type:
    """Build tool input schema for the LLM (no ``runtime`` — injected by ToolNode)."""
    return create_schema_from_function(
        func.__name__,
        func,
        filter_args=[*_filter_schema_args(func), "runtime"],
    )
