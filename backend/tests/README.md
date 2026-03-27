# Backend tests (`tests/`)

Automated tests for the FastAPI backend live under `backend/tests/`. They use **pytest**. Dev dependencies (`pytest`, `httpx`) are listed under `[project.optional-dependencies] dev` in `pyproject.toml`; install with `uv sync --extra dev` (or equivalent) before running tests.

## Running tests

From the `backend` directory:

```bash
uv run pytest
```

Useful variants:

```bash
uv run pytest -q                    # quiet
uv run pytest tests/test_safety.py  # single file
uv run pytest -k "retry"            # tests whose name contains "retry"
```

There is no project-level `pytest.ini` or `conftest.py` in this repo; defaults are pytest’s standard discovery (`test_*.py`, `Test*` classes, `test_*` functions).

## What each module covers

| File | Focus |
|------|--------|
| **`test_safety.py`** | **`app.core.safety`**: user message guard (prompt-injection-style phrases, length limits), monitor vs strict block mode, email send risk (allow/block domains, blocked content terms). Uses `Settings(...)` overrides for isolated policy configuration. |
| **`test_resilience.py`** | **`app.core.resilience.call_with_retry`**: success after transient failure, non-retryable errors, `max_attempts` edge cases, exhaustion after repeated retryable errors (with `time.sleep` patched to keep tests fast). |
| **`test_execution_summary.py`** | **`format_execution_summary`** in `app.agent.tools.execution`: successful draft creation text, retryable failure messaging. |
| **`test_execution_proposals.py`** | **`app.agent.tools.execution`**: `_extract_draft_id` for Gmail API response shapes, `execute_proposal` for unknown types and exception mapping (generic user-safe detail, no stack trace leak; Gmail draft mocked). |
| **`test_errors.py`** | **`app.core.errors`**: `AppError` / `UserSafeError` public message behavior, `map_exception_code` for app errors vs generic exceptions. |
| **`test_chat_api_delete.py`** | **`app.api.chat.delete_conversation`**: 404 for missing/wrong-user conversation, 500 when checkpoint delete fails, 500 with rollback when DB delete fails, success path verifying `delete_thread_checkpoints`, `db.delete`, `commit`. Uses mocks (`MagicMock`, `patch`)—no live database. |

## Relationship to production code

- **Safety and resilience** tests guard core policies used by the chat API and services without standing up the full HTTP stack.
- **Execution** tests target the agent’s **post-approval** Google mutation layer and summary formatting—critical for user-visible outcomes after HITL approval.
- **Chat delete** tests ensure conversation removal stays consistent between **SQLAlchemy** rows and **LangGraph** checkpoint storage.

## Adding new tests

- Prefer **unit tests** with mocks for I/O (DB, Google APIs) unless you add an integration harness.
- Keep `Settings(...)` construction explicit when testing configurable behavior.
- Name files `test_<area>.py` and functions `test_<behavior>()` for discovery.
