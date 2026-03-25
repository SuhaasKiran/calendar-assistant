"""Gmail proposal tools (queue drafts/sends until approval)."""

import uuid

from langchain.tools import ToolRuntime
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from app.agent.tools.tool_schema import args_schema_excluding_runtime

GMAIL_PROPOSAL_TYPES = frozenset({"create_email_draft", "send_email"})


def build_gmail_proposal_tools() -> list:
    """Tools that queue Gmail mutations."""

    def propose_create_email_draft(
        to: str,
        subject: str,
        body: str,
        runtime: ToolRuntime,
    ) -> Command:
        """Queue creating a Gmail draft (requires approval before creation)."""
        pid = str(uuid.uuid4())
        proposal: dict = {
            "type": "create_email_draft",
            "id": pid,
            "to": to,
            "subject": subject,
            "body": body,
        }
        return Command(
            update={
                "pending_proposals": [proposal],
                "messages": [
                    ToolMessage(
                        content=f"Queued draft proposal {pid} to {to}. Awaiting approval.",
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
        """Queue sending an email (requires explicit approval)."""
        pid = str(uuid.uuid4())
        proposal: dict = {
            "type": "send_email",
            "id": pid,
            "to": to,
            "subject": subject,
            "body": body,
        }
        return Command(
            update={
                "pending_proposals": [proposal],
                "messages": [
                    ToolMessage(
                        content=f"Queued send-email proposal {pid} to {to}. Awaiting approval.",
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
