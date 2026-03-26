from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load configuration from the environment and optional `.env` file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Calendar Assistant API"

    # Comma-separated origins; include every scheme/host/port you open the SPA on (credentialed CORS).
    cors_origins: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        description="Allowed browser origins for CORS",
    )

    google_client_id: str | None = None
    google_client_secret: str | None = None
    # Must match Google Cloud Console OAuth redirect and this app's callback route.
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"
    # Browser redirect after successful OAuth (React dev server).
    oauth_post_login_redirect: str = "http://localhost:5173"
    secret_key: str = ""
    database_url: str = "sqlite:///./app/db/databases/calendar_assistant.db"
    # SQLite file for LangGraph checkpoints (relative to process cwd, usually `backend/`).
    langgraph_checkpoint_path: str = "app/agent/db/langgraph_checkpoints.sqlite"

    # LLM: set `llm_provider` and the matching credentials / model names below.
    llm_provider: Literal["openai", "anthropic", "ollama"] = "openai"
    llm_temperature: float = 0.0

    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-3-5-haiku-20241022"

    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"

    # Google API HTTP client (Calendar, Gmail)
    google_http_timeout_seconds: float = 30.0
    google_api_max_retries: int = 3
    google_api_retry_base_delay_seconds: float = 0.5
    google_api_retry_max_delay_seconds: float = 8.0

    # LLM reliability
    llm_max_retries: int = 2
    llm_request_timeout_seconds: float = 45.0

    # Chat/API resilience
    chat_stream_timeout_seconds: float = 90.0
    api_retry_budget_per_request: int = 6
    reliability_features_enabled: bool = True

    # Safety controls
    safety_guard_enabled: bool = True
    safety_guard_strict_block: bool = True
    safety_max_input_chars: int = 6000
    safety_blocked_terms: str = (
        "ignore previous instructions,"
        "reveal system prompt,"
        "developer message,"
        "exfiltrate,"
        "steal credentials,"
        "malware,"
        "ransomware,"
        "phishing,"
        "social security number,"
        "credit card number"
    )
    safety_email_blocked_terms: str = (
        "wire transfer,"
        "bank account password,"
        "gift cards,"
        "crypto seed phrase,"
        "bypass security"
    )
    send_email_allowed_domains: str = ""
    send_email_blocked_domains: str = ""
    send_email_require_confirmation: bool = True

    session_cookie_name: str = "session"
    session_cookie_max_age_seconds: int = 60 * 60 * 24 * 7  # 7 days
    oauth_state_cookie_name: str = "oauth_state"
    oauth_state_max_age_seconds: int = 600

    # LangSmith (LangChain tracing): https://docs.smith.langchain.com
    langchain_tracing_v2: bool = Field(
        default=False,
        description="If true, send LangGraph / LLM traces to LangSmith (set LANGCHAIN_API_KEY).",
    )
    langchain_api_key: str | None = Field(
        default=None,
        description="LangSmith API key (also accepted as LANGCHAIN_API_KEY in .env).",
    )
    langchain_project: str | None = Field(
        default=None,
        description="LangSmith project name for grouping runs.",
    )
    langchain_endpoint: str | None = Field(
        default=None,
        description="Optional LangSmith API base URL (self-hosted); default is cloud.",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def safety_blocked_terms_list(self) -> list[str]:
        return [t.strip().lower() for t in self.safety_blocked_terms.split(",") if t.strip()]

    @property
    def safety_email_blocked_terms_list(self) -> list[str]:
        return [t.strip().lower() for t in self.safety_email_blocked_terms.split(",") if t.strip()]

    @property
    def send_email_allowed_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.send_email_allowed_domains.split(",") if d.strip()]

    @property
    def send_email_blocked_domains_list(self) -> list[str]:
        return [d.strip().lower() for d in self.send_email_blocked_domains.split(",") if d.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
