"""
Export compiled LangGraph flowcharts as images via ``get_graph()`` → Mermaid → PNG.

Default rendering uses the public Mermaid.ink API (requires network). For offline use,
call :func:`graph_mermaid_source` or :func:`save_graph_mermaid` and render locally.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def save_graph_png(
    compiled: Any,
    output_path: str | Path,
    *,
    config: Any | None = None,
    xray: int | bool = False,
    mkdir: bool = True,
    **draw_mermaid_png_kwargs: Any,
) -> Path:
    """
    Save a PNG flowchart for a compiled graph (``StateGraph.compile()``, etc.).

    Uses ``compiled.get_graph(config=..., xray=...).draw_mermaid_png(...)``.

    Parameters
    ----------
    compiled:
        A compiled LangGraph runnable (must implement ``get_graph``).
    output_path:
        File path ending in ``.png`` (or any extension; PNG bytes are written).
    config:
        Optional ``RunnableConfig`` passed to ``get_graph``.
    xray:
        Passed to ``get_graph`` to include nested subgraphs when True or > 0.
    mkdir:
        Create parent directories if missing.
    **draw_mermaid_png_kwargs:
        Forwarded to ``langchain_core.runnables.graph.Graph.draw_mermaid_png``,
        e.g. ``wrap_label_n_words``, ``draw_method``, ``max_retries``, ``proxies``.

    Returns
    -------
    Path
        The path written.
    """
    path = Path(output_path)
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    drawable = compiled.get_graph(config=config, xray=xray)
    png_bytes = drawable.draw_mermaid_png(
        output_file_path=None,
        **draw_mermaid_png_kwargs,
    )
    path.write_bytes(png_bytes)
    return path


def graph_mermaid_source(
    compiled: Any,
    *,
    config: Any | None = None,
    xray: int | bool = False,
    **draw_mermaid_kwargs: Any,
) -> str:
    """
    Return Mermaid diagram text (no HTTP). Useful for pasting into editors or CI without
    Mermaid.ink access.
    """
    return compiled.get_graph(config=config, xray=xray).draw_mermaid(**draw_mermaid_kwargs)


def save_graph_mermaid(
    compiled: Any,
    output_path: str | Path,
    *,
    config: Any | None = None,
    xray: int | bool = False,
    mkdir: bool = True,
    **draw_mermaid_kwargs: Any,
) -> Path:
    """Save Mermaid source to a ``.mmd`` / ``.mermaid`` file."""
    path = Path(output_path)
    if mkdir:
        path.parent.mkdir(parents=True, exist_ok=True)
    text = graph_mermaid_source(
        compiled, config=config, xray=xray, **draw_mermaid_kwargs
    )
    path.write_text(text, encoding="utf-8")
    return path


# Alias for callers who prefer the name from the feature request
build_graph = save_graph_png

__all__ = [
    "build_graph",
    "graph_mermaid_source",
    "save_graph_mermaid",
    "save_graph_png",
]
