"""Unit tests for delete_conversation in chat API."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.chat import delete_conversation
from app.db.models import Conversation


def _user(user_id: int = 1) -> MagicMock:
    u = MagicMock()
    u.id = user_id
    return u


def test_delete_conversation_not_found() -> None:
    db = MagicMock()
    db.get.return_value = None
    user = _user()

    with pytest.raises(HTTPException) as exc_info:
        delete_conversation("missing-id", db, user)
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Conversation not found"


def test_delete_conversation_wrong_user() -> None:
    conv = MagicMock()
    conv.user_id = 99
    db = MagicMock()
    db.get.return_value = conv
    user = _user()

    with pytest.raises(HTTPException) as exc_info:
        delete_conversation("cid", db, user)
    assert exc_info.value.status_code == 404


@patch("app.api.chat.delete_thread_checkpoints")
def test_delete_conversation_checkpoint_failure_raises_500(mock_cp: MagicMock) -> None:
    mock_cp.side_effect = OSError("disk error")
    conv = MagicMock()
    conv.user_id = 1
    db = MagicMock()
    db.get.return_value = conv
    user = _user()

    with pytest.raises(HTTPException) as exc_info:
        delete_conversation("cid", db, user)
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to delete conversation state"
    db.execute.assert_not_called()


@patch("app.api.chat.delete_thread_checkpoints")
def test_delete_conversation_db_failure_rolls_back(mock_cp: MagicMock) -> None:
    mock_cp.return_value = (1, 0)
    conv = MagicMock()
    conv.user_id = 1
    db = MagicMock()
    db.get.return_value = conv
    db.execute.side_effect = RuntimeError("db down")
    user = _user()

    with pytest.raises(HTTPException) as exc_info:
        delete_conversation("cid", db, user)
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Failed to delete conversation"
    db.rollback.assert_called_once()


@patch("app.api.chat.delete_thread_checkpoints")
def test_delete_conversation_success(mock_cp: MagicMock) -> None:
    mock_cp.return_value = (2, 3)
    conv = MagicMock()
    conv.user_id = 1
    db = MagicMock()
    db.get.return_value = conv
    user = _user()

    delete_conversation("thread-1", db, user)

    mock_cp.assert_called_once_with("thread-1")
    db.get.assert_called_once_with(Conversation, "thread-1")
    db.execute.assert_called_once()
    db.delete.assert_called_once_with(conv)
    db.commit.assert_called_once()
