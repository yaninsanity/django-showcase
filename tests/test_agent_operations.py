from django_showcase.agent.base import SeedPlanningRequest
from django_showcase.agent.operations import AgentWarningCollector, safe_plan_frontend_routes, safe_plan_seed
from django_showcase.discovery.frontend import FrontendRoute
from django_showcase.seed.plan import ModelSeed, SeedPlan
from django_showcase.seed.providers.agentic import AgenticProvider
from django_showcase.agent.guardrails import SeedPlanGuardrails


class FailingAgent:
    name = "failing"

    def plan_seed(self, request: SeedPlanningRequest) -> SeedPlan:
        raise RuntimeError("boom")

    def plan_frontend_routes(self, framework: str, snippets: str) -> list[FrontendRoute]:
        raise RuntimeError("boom")


def test_safe_plan_frontend_routes_falls_back_on_error():
    provider = AgenticProvider(agent=FailingAgent(), guardrails=SeedPlanGuardrails())
    warnings = AgentWarningCollector()

    routes = safe_plan_frontend_routes(provider, "react", "const routes = []", warnings)

    assert routes == []
    assert warnings.messages


def test_safe_plan_seed_returns_fallback_on_error():
    provider = AgenticProvider(agent=FailingAgent(), guardrails=SeedPlanGuardrails())
    warnings = AgentWarningCollector()
    fallback = SeedPlan(models=[ModelSeed(model="shop.Order", count=1, fields={"status": "pending"})])

    result = safe_plan_seed(
        provider,
        SeedPlanningRequest(scenario_id="orders.pending", goal="Show pending orders"),
        fallback=fallback,
        warnings=warnings,
    )

    assert result == fallback
    assert warnings.messages