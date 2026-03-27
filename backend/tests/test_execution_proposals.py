"""Tests for proposal execution helpers and execute_proposal edge cases."""

from unittest.mock import MagicMock, patch

from app.agent.tools.execution import (
    GENERIC_EXECUTION_ERROR,
    _extract_draft_id,
    execute_proposal,
)
from app.config import Settings


def test_extract_draft_id_top_level_id() -> None:
    assert _extract_draft_id({"id": "draft-abc", "message": {"id": "msg-1"}}) == "draft-abc"


def test_extract_draft_id_nested_draft() -> None:
    assert _extract_draft_id({"draft": {"id": "draft-xyz"}}) == "draft-xyz"


def test_extract_draft_id_invalid_returns_none() -> None:
    assert _extract_draft_id({}) is None
    assert _extract_draft_id({"draft": {}}) is None
    assert _extract_draft_id("not-a-dict") is None


def test_execute_proposal_unknown_type() -> None:
    db = MagicMock()
    settings = Settings()
    out = execute_proposal(
        db,
        1,
        settings,
        default_timezone="UTC",
        proposal={"type": "not_a_real_type", "id": "p1"},
    )
    assert out["ok"] is False
    assert out["error_code"] == "UNKNOWN_PROPOSAL_TYPE"
    assert out["retryable"] is False


@patch("app.agent.tools.execution.gmail_client.create_email_draft")
def test_execute_proposal_exception_maps_to_generic_detail(
    mock_draft: MagicMock,
) -> None:
    mock_draft.side_effect = RuntimeError("internal stack trace must not leak")
    db = MagicMock()
    settings = Settings()
    out = execute_proposal(
        db,
        1,
        settings,
        default_timezone="UTC",
        proposal={
            "type": "create_email_draft",
            "id": "p2",
            "to": "a@b.com",
            "subject": "s",
            "body": "b",
        },
    )
    assert out["ok"] is False
    assert out["error_code"] == "EXECUTION_EXCEPTION"
    assert out["detail"] == GENERIC_EXECUTION_ERROR
    assert "stack trace" not in (out["detail"] or "")
