"""LangGraph Sqlite checkpointer (thread_id = conversation_id)."""

from __future__ import annotations

import sqlite3
from functools import lru_cache
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver

from app.config import Settings, get_settings


def _resolved_sqlite_path(path: str) -> str:
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = Path.cwd() / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return str(p)


@lru_cache
def _saver_for_path(path: str) -> SqliteSaver:
    resolved = _resolved_sqlite_path(path)
    conn = sqlite3.connect(resolved, check_same_thread=False)
    return SqliteSaver(conn)


def get_checkpointer(settings: Settings | None = None) -> SqliteSaver:
    s = settings or get_settings()
    return _saver_for_path(s.langgraph_checkpoint_path)


def delete_thread_checkpoints(
    thread_id: str,
    *,
    settings: Settings | None = None,
) -> tuple[int, int]:
    """
    Delete all checkpoint/write rows for a thread id (conversation id).

    Returns:
        tuple[int, int]: (deleted_checkpoints, deleted_writes)
    """
    s = settings or get_settings()
    path = _resolved_sqlite_path(s.langgraph_checkpoint_path)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.execute("DELETE FROM writes WHERE thread_id = ?", (thread_id,))
        writes_deleted = cur.rowcount if cur.rowcount is not None else 0
        cur.execute("DELETE FROM checkpoints WHERE thread_id = ?", (thread_id,))
        checkpoints_deleted = cur.rowcount if cur.rowcount is not None else 0
        conn.commit()
        return checkpoints_deleted, writes_deleted
    finally:
        conn.close()
