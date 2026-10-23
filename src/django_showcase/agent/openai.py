from __future__ import annotations

import json
import os

from django.core.exceptions import ImproperlyConfigured, ValidationError

from django_showcase.agent.base import SeedPlanningRequest
from django_showcase.agent.frontend import parse_frontend_routes
from django_showcase.agent.prompts import (
    PromptBundle,
    render_frontend_route_prompt,
    render_seed_planner_prompt,
)
from django_showcase.discovery.frontend import FrontendRoute
from django_showcase.seed.plan import ModelSeed, RelationshipSeed, SeedPlan


class OpenAIAgentProvider:
    name = "openai"

    def __init__(
        self,
        model: str = "gpt-4.1-mini",
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        prompts: PromptBundle | None = None,
    ) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise ImproperlyConfigured(
                "The OpenAI provider requires the ai extra: "
                'pip install "django-showcase[ai]"'
            ) from exc
        if not os.environ.get("OPENAI_API_KEY"):
            raise ImproperlyConfigured(
                "OPENAI_API_KEY is required for --agentic with " "provider=openai."
            )
        self._client = OpenAI(timeout=timeout_seconds, max_retries=max_retries)
        self._model = model
        self._prompts = prompts or PromptBundle()

    def plan_seed(self, request: SeedPlanningRequest) -> SeedPlan:
        response = self._client.responses.create(
            model=self._model,
            instructions=self._prompts.seed_planner_system,
            input=render_seed_planner_prompt(
                request,
                template=self._prompts.seed_planner_user,
            ),
        )
        return parse_seed_plan(response.output_text)

    def plan_frontend_routes(
        self, framework: str, snippets: str
    ) -> list[FrontendRoute]:
        response = self._client.responses.create(
            model=self._model,
            instructions=self._prompts.frontend_route_system,
            input=render_frontend_route_prompt(
                framework,
                snippets,
                template=self._prompts.frontend_route_user,
            ),
        )
        return parse_frontend_routes(response.output_text)


def parse_seed_plan(raw: str) -> SeedPlan:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Agent response is not valid JSON.") from exc
    return SeedPlan(
        models=[
            ModelSeed(
                model=str(item["model"]),
                count=int(item.get("count", 1)),
                fields=dict(item.get("fields", {})),
            )
            for item in data.get("models", [])
        ],
        relationships=[
            RelationshipSeed(
                source=str(item["source"]),
                target=str(item["target"]),
            )
            for item in data.get("relationships", [])
        ],
    )
