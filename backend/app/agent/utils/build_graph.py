"""
Export compiled LangGraph flowcharts as images via ``get_graph()`` → Mermaid → PNG.

Default rendering uses the public Mermaid.ink API (requires network). For offline use,
call :func:`graph_mermaid_source` or :func:`save_graph_mermaid` and render locally.
"""

from __future__ import annotations

import argparse
import sys
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


def main() -> int:
    """
    Build the compiled assistant graph and export a PNG image.

    This compiles the graph via existing app builders, so it respects the same
    settings, tools, and routing used in runtime.
    """
    parser = argparse.ArgumentParser(
        description="Generate a PNG flowchart for app.agent.graphs.react_graph."
    )
    parser.add_argument(
        "--output",
        default="react_assistant_graph.png",
        help="Output PNG path (default: react_assistant_graph.png)",
    )
    parser.add_argument(
        "--mermaid-output",
        default=None,
        help="Optional path to save Mermaid source (.mmd/.mermaid).",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=1,
        help="User id used to initialize graph-bound tools (default: 1).",
    )
    parser.add_argument(
        "--timezone",
        default="UTC",
        help="Default user timezone used in prompts/execution context.",
    )
    parser.add_argument(
        "--approval-from-email",
        default=None,
        help="Optional From address shown in email approval UI.",
    )
    parser.add_argument(
        "--user-email",
        default=None,
        help="Optional user email included in dynamic prompt context.",
    )
    parser.add_argument(
        "--xray",
        type=int,
        default=0,
        help="Set >0 to include deeper nested graph detail in render.",
    )
    args = parser.parse_args()

    # Ensure `import app...` works when executed as a script.
    backend_root = Path(__file__).resolve().parents[3]
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))

    from app.agent.graphs.chat_agent import build_chat_agent
    from app.config import get_settings
    from app.db.session import SessionLocal

    settings = get_settings()
    db = SessionLocal()
    try:
        compiled = build_chat_agent(
            settings=settings,
            db=db,
            user_id=args.user_id,
            user_timezone=args.timezone,
            approval_from_email=args.approval_from_email,
            user_email=args.user_email,
        )
        png_path = save_graph_png(compiled, args.output, xray=bool(args.xray))
        print(f"Graph PNG written to: {png_path}")
        if args.mermaid_output:
            mermaid_path = save_graph_mermaid(compiled, args.mermaid_output, xray=bool(args.xray))
            print(f"Mermaid source written to: {mermaid_path}")
    except Exception as exc:
        print(
            "Failed to build or render graph. Ensure backend dependencies and LLM settings "
            f"are available (.env). Error: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        db.close()
    return 0


__all__ = [
    "build_graph",
    "graph_mermaid_source",
    "main",
    "save_graph_mermaid",
    "save_graph_png",
]


if __name__ == "__main__":
    raise SystemExit(main())
