# Dobo Assistant

## 1. About

Dobo is a smart assistant that helps you manage your schedule and communication through simple chat.

It connects to your calendar and email, understands what you ask in everyday language, and helps you get things done.

With Dobo, you can:
- check your schedule and upcoming events  
- create, update, or organize meetings  
- draft and send emails  
- keep track of conversations over time  
- review and confirm important actions before they happen  

## 2. Features

### a. Functional Features

- Google OAuth login and session-based authentication.
- Chat interface with protected routes and conversation history.
- Streaming assistant responses over Server-Sent Events (SSE).
- Human-in-the-loop (HITL) interrupt and resume support for action approval.
- Calendar and Gmail-oriented assistant tooling through Google APIs.
- Conversation management APIs (list messages, list conversations, delete conversations).

### b. Non-Functional Features

- Safety guardrails for prompt injection, harmful content, oversized input, and sensitive email actions.
- Retry and timeout controls in both frontend API requests and backend service calls.
- Structured error responses with request IDs for troubleshooting.
- Config-driven behavior through environment variables and typed settings.
- Optional LangSmith tracing support for observability.
- Modular backend architecture (API, services, agent graphs, safety, resilience, DB layers).

## 3. Tech Stack

### a. Frontend

- React 19 + TypeScript
- Vite
- React Router
- Fetch API with credentialed requests and retry/timeout handling
- ESLint (TypeScript + React rules)

### b. Backend

- Python 3.11+
- FastAPI + Uvicorn
- SQLAlchemy
- Pydantic Settings
- LangGraph + LangChain ecosystem
- Google OAuth + Google Calendar/Gmail APIs
- JWT-based session token for auth cookies
- SQLite (application data + LangGraph checkpoint persistence)

The **assistant agent** lives under `app/agent` (see `backend/app/agent/README.md`). Main features:

- **LangGraph ReAct loop** — model alternates between reasoning and tool calls until the turn completes or pauses for approval.
- **Calendar reads** — list/get events via Google Calendar tools before proposing changes.
- **Proposal queue** — create/update/delete events and email drafts/sends are **proposed** first; nothing mutates Google until the user approves.
- **Human-in-the-loop (HITL)** — interrupts surface pending actions for approve / edit / reject; execution runs only after approval.
- **Resumable state** — SQLite checkpoints per conversation (`thread_id`) so interrupted flows can resume.
- **Streaming to the client** — SSE carries interrupt payloads and final assistant text from the graph to the chat API.
- **Configurable LLM** — OpenAI, Anthropic, or Ollama via settings.
- **Guardrails in the loop** — rolling conversation summary, bounded message window, and tool-loop limits to avoid runaway tool use.

## 4. Setup (Prerequisites, Installation)

### Prerequisites

- Node.js 18+ and npm
- Python 3.11+
- `uv` (Python package/dependency manager)
- Google Cloud OAuth credentials (Web client) for Google login
- At least one LLM provider configured:
  - OpenAI (`OPENAI_API_KEY`)
  - Anthropic (`ANTHROPIC_API_KEY`)

### a. Frontend

1. Open a terminal in `frontend`.
2. Copy env template:
   - `cp .env.example .env`
3. Install dependencies:
   - `npm install`
4. Start dev server:
   - `npm run dev`

Notes:
- By default, frontend API calls can use Vite proxy/same-origin behavior in dev.
- If needed, set `VITE_API_BASE_URL` in `frontend/.env`.

### b. Backend

1. Open a terminal in `backend`.
2. Copy env template:
   - `cp .env.example .env`
3. Fill required values in `backend/.env`, especially:
   - `GOOGLE_CLIENT_ID`
   - `GOOGLE_CLIENT_SECRET`
   - `GOOGLE_REDIRECT_URI` (must match your Google OAuth config)
   - `OAUTH_POST_LOGIN_REDIRECT`
   - `SECRET_KEY`
   - `LLM_PROVIDER` and related model/API key values
4. Sync/install dependencies:
   - `uv sync`
5. Start API server:
   - `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

Recommended local URL:
- Backend API: `http://localhost:8000`
- Health check: `http://localhost:8000/health`
- Frontend app: `http://localhost:5173`

## 5. Architecture

High-level flow:

1. User opens the React app and authenticates via Google OAuth.
2. Frontend sends authenticated requests (cookies included) to FastAPI endpoints.
3. Chat requests hit `/chat` APIs and are streamed back as SSE events.
4. Backend builds/runs a LangGraph chat agent with user context and conversation thread ID.
5. Agent can route through domain tools (calendar/gmail) and may emit HITL interrupts for confirmation.
6. Messages, users, and tokens persist in SQLite via SQLAlchemy; graph checkpoints persist separately for resumable workflows.

Core backend layers:

- `app/api`: HTTP routes (`auth`, `chat`, `health`)
- `app/agent`: Graph builder, routing, units, tool schemas, streaming
- `app/services`: Google OAuth/Calendar/Gmail clients
- `app/core`: safety, resilience, request context, error mapping
- `app/db`: SQLAlchemy models/session/bootstrap
- `app/config`: environment-driven typed settings

Core frontend layers:

- `src/components`: chat UI, auth/session UI, composer/message list
- `src/api`: auth/chat/client request utilities
- `src/context` + `src/hooks`: session state and helper hooks
- `src/config.ts`: API base URL resolution by environment

## 6. Testing

### Backend

Run tests from `backend`:

- `uv run pytest`

Current tests validate key reliability and safety behavior, including:
- retry behavior in resilience helpers
- safety policy enforcement for risky prompts and email constraints
- execution summary logic

### Frontend

No dedicated frontend test suite is currently configured in scripts.
Use these quality checks from `frontend`:

- Lint: `npm run lint`
- Production build check: `npm run build`

For manual verification:
- authenticate with Google
- send a chat prompt and verify streaming response
- verify conversation list/history rendering
- verify interrupt/resume flows when assistant actions require confirmation
