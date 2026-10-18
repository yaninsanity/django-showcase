import pytest
from django.core.exceptions import ValidationError

from django_showcase.agent.base import SeedPlanningRequest
from django_showcase.agent.cache import SeedPlanCache
from django_showcase.agent.guardrails import SeedPlanGuardrails
from django_showcase.agent.openai import parse_seed_plan
from django_showcase.agent.prompts import render_seed_planner_prompt
from django_showcase.agent.tools import build_schema_summary
from django_showcase.seed.plan import ModelSeed, SeedPlan
from django_showcase.seed.providers.agentic import AgenticProvider


class StubAgent:
    name = "stub"

    def __init__(self, plan: SeedPlan) -> None:
        self._plan = plan
        self.calls = 0

    def plan_seed(self, request: SeedPlanningRequest) -> SeedPlan:
        self.calls += 1
        return self._plan


def test_guardrails_reject_unknown_model():
    plan = SeedPlan(models=[ModelSeed(model="ghost.Ghost", count=1)])
    with pytest.raises(ValidationError, match="Unknown model"):
        SeedPlanGuardrails().check(plan)


def test_guardrails_reject_invalid_choice():
    plan = SeedPlan(
        models=[ModelSeed(model="shop.Order", count=1, fields={"status": "cancelled"})]
    )
    with pytest.raises(ValidationError, match="Invalid choice"):
        SeedPlanGuardrails().check(plan)


def test_guardrails_reject_excessive_volume():
    plan = SeedPlan(
        models=[ModelSeed(model="shop.Order", count=10, fields={"status": "pending"})]
    )
    with pytest.raises(ValidationError, match="max_objects"):
        SeedPlanGuardrails(max_objects=5).check(plan)


def test_agentic_provider_caches_plans(tmp_path):
    valid_plan = SeedPlan(
        models=[ModelSeed(model="shop.Order", count=3, fields={"status": "paid"})]
    )
    agent = StubAgent(valid_plan)
    provider = AgenticProvider(
        agent=agent,
        guardrails=SeedPlanGuardrails(),
        cache=SeedPlanCache(tmp_path / "cache"),
    )
    request = SeedPlanningRequest(scenario_id="orders.paid", goal="Show paid orders")

    first = provider.plan(request)
    second = provider.plan(request)

    assert agent.calls == 1
    assert first.models[0].count == second.models[0].count == 3


def test_prompt_contains_goal_and_schema():
    request = SeedPlanningRequest(
        scenario_id="orders.failed",
        goal="Show several failed orders.",
        schema_summary=build_schema_summary(),
    )
    prompt = render_seed_planner_prompt(request)

    assert "orders.failed" in prompt
    assert "Show several failed orders." in prompt
    assert "shop.Order" in prompt


def test_parse_seed_plan_rejects_non_json():
    with pytest.raises(ValidationError):
        parse_seed_plan("DROP TABLE orders;")


def test_parse_seed_plan_builds_structured_plan():
    plan = parse_seed_plan(
        (
            '{"models": [{"model": "shop.Order", "count": 2, '
            '"fields": {"status": "pending"}}]}'
        )
    )
    assert plan.models[0].model == "shop.Order"
    assert plan.models[0].count == 2
