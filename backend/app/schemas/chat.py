"""Chat API request/response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    """Send a user message or resume after a human-in-the-loop interrupt."""

    message: str | None = None
    conversation_id: str | None = Field(
        default=None,
        description="Existing conversation UUID; omit to start a new thread.",
    )
    resume: bool = Field(
        default=False,
        description="If true, `resume_value` is passed to LangGraph Command(resume=...).",
    )
    resume_value: Any = Field(
        default=None,
        description="Payload for interrupt resume (e.g. true/false for approval, or clarification text).",
    )

    @model_validator(mode="after")
    def _validate_body(self) -> ChatRequest:
        if self.resume:
            if self.resume_value is None:
                raise ValueError("resume_value is required when resume is true")
        else:
            if self.message is None or not str(self.message).strip():
                raise ValueError("message is required when resume is false")
        return self

