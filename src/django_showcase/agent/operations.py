from __future__ import annotations

from dataclasses import dataclass, field

from django_showcase.agent.base import SeedPlanningRequest
from django_showcase.discovery.frontend import FrontendRoute
from django_showcase.seed.plan import SeedPlan
from django_showcase.seed.providers.agentic import AgenticProvider


@dataclass(slots=True)
class AgentWarningCollector:
    messages: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.messages.append(message)


def safe_plan_frontend_routes(
    provider: AgenticProvider | None,
    framework: str,
    snippets: str,
    warnings: AgentWarningCollector,
) -> list[FrontendRoute]:
    if provider is None:
        return []
    try:
        return provider.agent.plan_frontend_routes(framework, snippets)
    except Exception as exc:
        warnings.warn(
            "Agent frontend discovery failed; using deterministic routes only "
            f"({exc})."
        )
        return []


def safe_plan_seed(
    provider: AgenticProvider | None,
    request: SeedPlanningRequest,
    fallback: SeedPlan | None,
    warnings: AgentWarningCollector,
) -> SeedPlan | None:
    if provider is None:
        return fallback
    try:
        return provider.plan(request)
    except Exception as exc:
        warnings.warn(
            "Agent seed planning failed for "
            f"{request.scenario_id}; using fallback ({exc})."
        )
        return fallback
