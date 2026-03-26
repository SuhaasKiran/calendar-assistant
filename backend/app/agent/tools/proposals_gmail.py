"""Gmail tools: draft via approval-gated proposal, send now."""

import logging
import re
import uuid
from email.utils import parseaddr

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.safety import evaluate_email_send_risk
from app.agent.tools.tool_schema import args_schema_excluding_runtime
from app.services import gmail_client

GMAIL_PROPOSAL_TYPES = frozenset({"create_email_draft"})
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
logger = logging.getLogger(__name__)


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
        confirm_send: bool = False,
    ) -> Command:
        """Send an email immediately without approval."""
        recipient = _normalize_recipient_email(to)
        if not recipient:
            return _clarify_recipient(runtime, to)
        if settings.send_email_require_confirmation and not confirm_send:
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            content=(
                                "Send blocked: explicit confirmation is required. "
                                "Re-run this tool with `confirm_send=true` after verifying recipient and content."
                            ),
                            tool_call_id=runtime.tool_call_id or "",
                        ),
                        AIMessage(
                            content=(
                                "For safety, I need explicit confirmation before sending. "
                                "If this email is ready, tell me to send it now and I will proceed with confirmation."
                            )
                        ),
                    ],
                }
            )
        # # Evaluates if email domain is not blocked
        # risk = evaluate_email_send_risk(
        #     recipient=recipient,
        #     subject=subject,
        #     body=body,
        #     settings=settings,
        # )
        # if not risk.allowed:
        #     logger.warning(
        #         "blocked_send_email user_id=%s recipient=%s reason=%s code=%s",
        #         user_id,
        #         recipient,
        #         risk.reason,
        #         risk.code,
        #     )
        #     return Command(
        #         update={
        #             "messages": [
        #                 ToolMessage(
        #                     content=f"Send blocked by safety policy: {risk.reason}",
        #                     tool_call_id=runtime.tool_call_id or "",
        #                 ),
        #                 AIMessage(
        #                     content=(
        #                         "I cannot send this email as-is due to safety policy. "
        #                         "Please revise the recipient/content and try again."
        #                     )
        #                 ),
        #             ],
        #         }
        #     )

        out = gmail_client.send_email(
            db,
            user_id,
            settings,
            to=recipient,
            subject=subject,
            body=body,
        )
        msg_id = str((out or {}).get("id") or "unknown")
        thread_id = str((out or {}).get("threadId") or "unknown")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content=f"Sent email {msg_id} (thread {thread_id}) to {recipient}.",
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
