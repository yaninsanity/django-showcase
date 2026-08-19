from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from django_showcase.discovery.frontend import FrontendRoute
from django_showcase.seed.plan import SeedPlan


@dataclass(slots=True)
class SeedPlanningRequest:
    scenario_id: str
    goal: str
    schema_summary: dict[str, object] = field(default_factory=dict)


class AgentProvider(Protocol):
    name: str

    def plan_seed(self, request: SeedPlanningRequest) -> SeedPlan: ...

    def plan_frontend_routes(self, framework: str, snippets: str) -> list[FrontendRoute]: ...
