from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from django_showcase.agent.base import AgentProvider
from django_showcase.agent.prompts import PromptBundle


def load_agent_provider(
    provider_name: str,
    *,
    model: str = "gpt-4.1-mini",
    timeout_seconds: float = 30.0,
    max_retries: int = 2,
    prompt_overrides: dict[str, str] | None = None,
) -> AgentProvider:
    if provider_name == "openai":
        from django_showcase.agent.openai import OpenAIAgentProvider

        return OpenAIAgentProvider(
            model=model,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            prompts=PromptBundle.from_overrides(prompt_overrides),
        )
    raise ImproperlyConfigured(f"Unknown agent provider: {provider_name!r}")
