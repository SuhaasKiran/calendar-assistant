# Agent package (`app.agent`)

This package implements the **LangGraph-based calendar assistant**: tool bindings, ReAct-style reasoning loop, human-in-the-loop (HITL) approval for mutations, SQLite checkpointing per conversation, and helpers to stream results to the HTTP layer as Server-Sent Events (SSE).

## High-level architecture

1. **Entry point** — `build_chat_agent()` (`graphs/chat_agent.py`) builds the LLM, loads the Sqlite checkpointer, and compiles the **main** graph for one HTTP request. Tools close over the active SQLAlchemy `Session` and `user_id` so reads and writes stay scoped to the current user.
2. **Graph** — `build_calendar_assistant_graph()` (`graphs/builder.py`) wires **read tools**, **proposal tools** (queued writes), and **HITL tools** into `build_react_assistant_graph()` (`graphs/react_graph.py`): a single ReAct loop with **approval** and **execute** nodes.
3. **Persistence** — `thread_id` in LangGraph config is the **conversation id**. Checkpoints live in a SQLite file (`Settings.langgraph_checkpoint_path`); `delete_thread_checkpoints()` in `graphs/checkpoint.py` removes checkpoint rows when a conversation is deleted.
4. **API bridge** — `stream_graph_sse()` (`streaming/graph_stream.py`) runs `graph.stream(...)`, emits JSON lines for SSE (`interrupt`, `content`, `done`, `error`).

```text
HTTP /chat  →  build_chat_agent  →  compiled StateGraph
                      ↓
        [agent] ⇄ [tools] → [after_tools] → …
                      ↓
        [approval_gate] → interrupt (HITL)  OR  [execute_mutations]
                      ↓
        stream_graph_sse  →  SSE JSON lines  →  client
```

## Directory layout

| Path | Role |
|------|------|
| `graphs/` | State graph definition, routing, ReAct loop, optional unit subgraphs |
| `tools/` | LangChain tools: calendar reads, calendar/Gmail proposals, execution, HITL |
| `prompts/` | System and dynamic context prompts (`chat_system_prompt`, `chat_context_prompt`) |
| `streaming/` | SSE adapters: `stream_graph_sse`, `stream_agent_events` |
| `utils/` | `build_chat_model` (OpenAI / Anthropic / Ollama), optional graph PNG export (`build_graph.py`) |

## State (`graphs/state.py`)

`CalendarAgentState` is the graph’s **TypedDict** state:

- **`messages`** — LangChain message list with a bounded reducer (`MAX_MESSAGES_STATE`) so context does not grow without limit.
- **`pending_proposals`** — List of mutation dicts (`create_event`, `update_event`, `delete_event`, `create_email_draft`, `send_email`). A sentinel `{type: "__clear__"}` clears the list after approval/rejection or execution.
- **`conversation_summary` / rolling summary** — When message count exceeds `SUMMARY_TRIGGER_MESSAGES`, older turns are summarized; recent turns stay verbatim for the model.
- **`tool_rounds` / `tool_fingerprints`** — Guardrails against infinite or repeated tool loops (`routing.py`).
- **`resume_approved` / `approval_edit_requested`** — Drives routing after the user responds to an approval interrupt.

Proposal payloads are documented as `TypedDict` variants (`CreateEventProposal`, etc.) for consistency with `tools/execution.py`.

## Graph workflow (`graphs/react_graph.py`)

The compiled graph is built by **`build_react_assistant_graph`**. Typical node flow:

1. **`agent`** — Prepends a **system** message: static instructions from `prompts/chat.py`, plus **refreshed context** (e.g. user timezone, current local date/day, user email) and **conversation summary + recent transcript** from `chat_context_prompt`. Invokes the LLM with tools bound.
2. **Conditional from `agent`** — If the model requests tools → **`tools`** (LangGraph `ToolNode`). If there are **pending proposals** and no further tool calls → **`approval_gate`**. Otherwise → **END**.
3. **`tools` → `after_tools`** — Updates tool round counters and fingerprints; may set `loop_stopped` if limits are exceeded. Routing: if the only tool was `request_user_clarification` → **end_turn** (user sees clarification in chat); else back to **`agent`** or graceful stop.
4. **`approval_gate`** — Calls LangGraph **`interrupt()`** with a structured payload (proposals + human-readable summary). On resume: **approve** → **`execute_mutations`**; **edit** → clear proposals and return to **`agent`** with user feedback; **reject** → clear and end with a short assistant message.
5. **`execute_mutations`** — Runs `execute_all_proposals()` from `tools/execution.py` (Google Calendar / Gmail), clears proposals, appends execution summary to state.

**Standalone subgraphs** (`graphs/units/calendar.py`, `graphs/units/gmail.py`) reuse the same ReAct machinery with **`proposal_types_scope`** set to calendar-only or Gmail-only proposal types—useful for tests or future composition. Production uses the **combined** graph from `builder.py` (`proposal_types_scope=None`).

## Routing helpers (`graphs/routing.py`)

- **`route_after_tools`** — Stops the loop after a clarification-only tool call, or returns to the agent.
- **`route_after_approval`** — Sends approved work to `execute_mutations`, otherwise back to the agent for edits.
- **`check_tool_loop_limits`** — Enforces `MAX_TOOL_ROUNDS_PER_TURN` and repeated fingerprint limits.

## Tools (`tools/`)

| Layer | Purpose |
|-------|---------|
| **`build_agent_tools()`** (`tools/__init__.py`) | Composes **read calendar**, **proposal** (calendar + Gmail), and **HITL** tools. |
| **`read_calendar.py`** | Read-only Google Calendar access (list/get events). |
| **`proposals_calendar.py` / `proposals_gmail.py`** | Structured tools that **enqueue** create/update/delete events or email drafts/sends into `pending_proposals`—they do **not** mutate Google APIs directly until approved. |
| **`proposals.py`** | Re-exports calendar + Gmail proposal builders. |
| **`hitl.py`** | `request_user_clarification` — ends the tool loop with a user-visible question. |
| **`execution.py`** | **`execute_all_proposals` / `execute_proposal`** — runs approved proposals via `services/calendar_client` and `services/gmail_client`; **`format_execution_summary`** — user-facing text from result dicts. |
| **`common.py` / `tool_schema.py`** | Shared helpers (e.g. schema stripping for `ToolRuntime`). |

## Prompts (`prompts/chat.py`)

- **`chat_system_prompt`** — Role, intent taxonomy, scheduling rules, email rules, safety behavior, timezone and user preferences.
- **`chat_context_prompt`** — Injects rolling summary + recent turns (concatenated inside `react_graph` with live date/context).

## Checkpointing (`graphs/checkpoint.py`)

- **`get_checkpointer(settings)`** — Returns a cached **`SqliteSaver`** for the configured path; parent directories are created as needed.
- **`delete_thread_checkpoints(thread_id)`** — Deletes checkpoint rows for a conversation id (used when deleting a conversation from the API).

## Streaming (`streaming/`)

- **`stream_graph_sse`** — Primary path for `/chat`: streams **updates** mode, detects `__interrupt__` for HITL, then emits final assistant text or `done`. Errors yield a structured `error` line with `request_id`.
- **`stream_agent_events`** — Alternative async chunk bridge for token/chunk-style streaming (see module docstring).

## Utilities (`utils/`)

- **`llm.py`** — **`build_chat_model(settings)`** selects OpenAI, Anthropic, or Ollama from `Settings`.
- **`build_graph.py`** — Optional export of compiled graphs to Mermaid/PNG for documentation or debugging.

## How the HTTP layer uses this

- **`app.api.chat`** builds a graph per request with `build_chat_agent(...)`, passes `configurable.thread_id = conversation_id`, hydrates input from DB vs checkpoint as needed, and consumes **`stream_graph_sse`** for SSE.

## Design notes

- **One graph compile per request** avoids holding stale DB sessions across requests.
- **Proposals vs execution** keeps destructive or external side effects behind explicit user approval (except read paths).
- **Checkpoints** enable **resume** after interrupts and consistent `thread_id` semantics with the chat API.
