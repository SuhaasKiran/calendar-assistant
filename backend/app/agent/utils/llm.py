"""
Construct the chat model for the agent from `Settings.llm_provider`.
"""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.config import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    """
    Return a LangChain chat model for OpenAI, Anthropic (Claude), or Ollama.

    Raises:
        RuntimeError: if required credentials or settings are missing for the
            selected provider.
    """
    provider = settings.llm_provider
    temperature = settings.llm_temperature

    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("LLM provider is openai but OPENAI_API_KEY is not set")
        return ChatOpenAI(
            model=settings.openai_model,
            api_key=settings.openai_api_key,
            temperature=temperature,
        )

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "LLM provider is anthropic but ANTHROPIC_API_KEY is not set"
            )
        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            temperature=temperature,
        )

    if provider == "ollama":
        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            temperature=temperature,
        )

    raise RuntimeError(
        f"Unknown llm_provider {provider!r}; expected openai, anthropic, or ollama"
    )
