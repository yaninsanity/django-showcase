"""Single source of truth for every prompt sent to an agent provider."""
from __future__ import annotations

import json
from dataclasses import dataclass

from django_showcase.agent.base import SeedPlanningRequest

SEED_PLANNER_SYSTEM = (
    "You are a seed-data planner for a Django product showcase. "
    "Respond with a single JSON object matching this schema and nothing else: "
    '{"models": [{"model": "<app_label.ModelName>", "count": <int>, "fields": '
    '{"<field>": <value>}}], "relationships": [{"source": '
    '"<app_label.Model.field>", "target": "<app_label.Model>"}]}. '
    "Counts must be realistic and small. "
    "Never emit SQL, Python code, shell commands, or model names absent from "
    "the provided schema."
)

SEED_PLANNER_USER = """Scenario: {scenario_id}

Goal:
{goal}

Available schema (the only models and fields you may reference):
{schema}
"""

FRONTEND_ROUTE_SYSTEM = (
    "You extract user-facing routes from frontend source code for a product showcase. "
    "Respond with a single JSON object and nothing else: "
    '{"routes": [{"path": "/orders"}]}. '
    "Only include routes literally present in the source. "
    "Never include parameterized, wildcard, or invented routes."
)

FRONTEND_ROUTE_USER = """Framework: {framework}

Source excerpts:
{snippets}
"""


@dataclass(frozen=True, slots=True)
class PromptBundle:
    seed_planner_system: str = SEED_PLANNER_SYSTEM
    seed_planner_user: str = SEED_PLANNER_USER
    frontend_route_system: str = FRONTEND_ROUTE_SYSTEM
    frontend_route_user: str = FRONTEND_ROUTE_USER

    @classmethod
    def from_overrides(cls, overrides: dict[str, str] | None = None) -> "PromptBundle":
        overrides = overrides or {}
        return cls(
            seed_planner_system=overrides.get(
                "seed_planner_system", SEED_PLANNER_SYSTEM
            ),
            seed_planner_user=overrides.get("seed_planner_user", SEED_PLANNER_USER),
            frontend_route_system=overrides.get(
                "frontend_route_system", FRONTEND_ROUTE_SYSTEM
            ),
            frontend_route_user=overrides.get(
                "frontend_route_user", FRONTEND_ROUTE_USER
            ),
        )


def render_seed_planner_prompt(
    request: SeedPlanningRequest, template: str = SEED_PLANNER_USER
) -> str:
    return template.format(
        scenario_id=request.scenario_id,
        goal=request.goal.strip(),
        schema=json.dumps(
            request.schema_summary,
            indent=2,
            sort_keys=True,
        ),
    )


def render_frontend_route_prompt(
    framework: str,
    snippets: str,
    template: str = FRONTEND_ROUTE_USER,
) -> str:
    return template.format(framework=framework, snippets=snippets)
