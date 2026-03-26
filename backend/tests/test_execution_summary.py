"""Tests for formatting user-visible execution summaries."""

from app.agent.tools.execution import format_execution_summary


def test_execution_summary_includes_draft_creation() -> None:
    summary = format_execution_summary(
        [
            {
                "ok": True,
                "type": "create_email_draft",
                "detail": "Draft created",
                "to": "person@example.com",
                "subject": "Subject",
                "result": {"draft": {"id": "d1"}},
            }
        ]
    )
    assert "Email draft created." in summary
    assert "person@example.com" in summary


def test_execution_summary_marks_retryable_failures() -> None:
    summary = format_execution_summary(
        [
            {
                "ok": False,
                "type": "send_email",
                "detail": "Google API error (503)",
                "retryable": True,
            }
        ]
    )
    assert "Could not complete action" in summary
    assert "You can retry this action." in summary
