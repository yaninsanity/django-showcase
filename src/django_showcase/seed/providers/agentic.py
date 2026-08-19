from __future__ import annotations

from dataclasses import dataclass

from django_showcase.agent.base import AgentProvider, SeedPlanningRequest
from django_showcase.agent.cache import SeedPlanCache, plan_cache_key
from django_showcase.agent.guardrails import SeedPlanGuardrails
from django_showcase.seed.plan import SeedPlan


@dataclass(slots=True)
class AgenticProvider:
    agent: AgentProvider
    guardrails: SeedPlanGuardrails
    cache: SeedPlanCache | None = None

    name = "agentic"

    def plan(self, request: SeedPlanningRequest) -> SeedPlan:
        key = plan_cache_key(self.agent.name, request.goal, request.schema_summary)
        if self.cache and (cached := self.cache.get(key)) is not None:
            return cached
        plan = self.guardrails.check(self.agent.plan_seed(request))
        if self.cache:
            self.cache.set(key, plan)
        return plan
