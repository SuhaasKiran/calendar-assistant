"""Gmail tools: draft via approval-gated proposal, send now."""

import re
import uuid
from email.utils import parseaddr

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.config import Settings
from app.services import gmail_client
from app.agent.tools.tool_schema import args_schema_excluding_runtime

GMAIL_PROPOSAL_TYPES = frozenset({"create_email_draft"})
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _normalize_recipient_email(raw: str) -> str | None:
    text = str(raw or "").strip()
    if not text:
        return None
    _name, parsed = parseaddr(text)
    candidate = (parsed or text).strip()
    if not candidate or not EMAIL_RE.fullmatch(candidate):
        return None
    return candidate


def _clarify_recipient(runtime: ToolRuntime, raw_to: str) -> Command:
    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=(
                        "Cannot proceed: recipient email is missing or invalid. "
                        f"Provided value: {raw_to!r}."
                    ),
                    tool_call_id=runtime.tool_call_id or "",
                ),
                AIMessage(
                    content=(
                        "Please share the recipient's full email address (for example, "
                        "`jack@example.com`) so I can continue."
                    )
                ),
            ],
        }
    )


def build_gmail_proposal_tools(
    db: Session,
    user_id: int,
    settings: Settings,
) -> list:
    """Gmail tools: queue draft for approval, send immediately."""

    def propose_create_email_draft(
        to: str,
        subject: str,
        body: str,
        runtime: ToolRuntime,
    ) -> Command:
        """Queue creating a Gmail draft (requires approval)."""
        recipient = _normalize_recipient_email(to)
        if not recipient:
            return _clarify_recipient(runtime, to)

        pid = str(uuid.uuid4())
        proposal: dict = {
            "type": "create_email_draft",
            "id": pid,
            "to": recipient,
            "subject": subject,
            "body": body,
        }
        return Command(
            update={
                "pending_proposals": [proposal],
                "messages": [
                    ToolMessage(
                        content=f"Queued draft proposal {pid} to {recipient}. Awaiting approval.",
                        tool_call_id=runtime.tool_call_id or "",
                    )
                ],
            }
        )

    def propose_send_email(
        to: str,
        subject: str,
        body: str,
        runtime: ToolRuntime,
    ) -> Command:
        """Send an email immediately without approval."""
        recipient = _normalize_recipient_email(to)
        if not recipient:
            return _clarify_recipient(runtime, to)

        out = gmail_client.send_email(
            db,
            user_id,
            settings,
            to=recipient,
            subject=subject,
            body=body,
        )
        msg_id = str((out or {}).get("id") or "unknown")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Sent email {msg_id} to {recipient}.",
                        tool_call_id=runtime.tool_call_id or "",
                    )
                ],
            }
        )

    return [
        StructuredTool.from_function(
            propose_create_email_draft,
            infer_schema=False,
            args_schema=args_schema_excluding_runtime(propose_create_email_draft),
        ),
        StructuredTool.from_function(
            propose_send_email,
            infer_schema=False,
            args_schema=args_schema_excluding_runtime(propose_send_email),
        ),
    ]
