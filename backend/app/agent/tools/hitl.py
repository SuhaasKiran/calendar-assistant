"""Human-in-the-loop helper tools (clarification)."""

from langchain.tools import ToolRuntime
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.types import Command

from app.agent.tools.tool_schema import args_schema_excluding_runtime


def build_hitl_tools() -> list:
    def request_user_clarification(
        question: str,
        runtime: ToolRuntime,
    ) -> Command:
        """Ask the user a clarifying question in chat before continuing. Use when requirements are ambiguous."""
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="Awaiting your reply in the chat.",
                        tool_call_id=runtime.tool_call_id or "",
                    ),
                    AIMessage(content=question),
                ],
            }
        )

    return [
        StructuredTool.from_function(
            request_user_clarification,
            infer_schema=False,
            args_schema=args_schema_excluding_runtime(request_user_clarification),
        ),
    ]
