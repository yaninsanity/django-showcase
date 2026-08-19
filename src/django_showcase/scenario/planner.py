from __future__ import annotations

from dataclasses import dataclass
import re

from django_showcase.discovery.models import ModelMetadata
from django_showcase.discovery.urls import RouteInfo
from django_showcase.discovery.views import ViewMetadata
from django_showcase.scenario.graph import Module, ScenarioGraph
from django_showcase.scenario.ranking import score_scenario
from django_showcase.scenario.scenario import Scenario
from django_showcase.seed.plan import ModelSeed, SeedPlan, SeedSpec


@dataclass(slots=True)
class PlannerInputs:
    routes: list[RouteInfo]
    views: list[ViewMetadata]
    models: list[ModelMetadata]
    max_scenarios_per_module: int
    max_choices_per_field: int


class ScenarioPlanner:
    def build_graph(self, inputs: PlannerInputs) -> ScenarioGraph:
        graph = ScenarioGraph()
        view_index = {view.route_name: view for view in inputs.views}
        module_candidates: dict[str, list[Scenario]] = {}

        for route in inputs.routes:
            module_id = route.module_id or "core"
            module = graph.modules.setdefault(
                module_id,
                Module(
                    id=module_id,
                    title=module_id.replace("_", " ").title(),
                    routes=[],
                ),
            )
            module.routes.append(route.name)

            candidates = self._build_candidates(
                route,
                view_index.get(route.name),
                inputs.models,
                inputs.max_choices_per_field,
            )
            module_candidates.setdefault(module_id, []).extend(candidates)

        for module_id, candidates in module_candidates.items():
            deduped = _dedupe_scenarios(candidates)
            graph.module_candidate_counts[module_id] = len(deduped)
            baseline_ids = {
                scenario.id
                for scenario in deduped
                if scenario.id.endswith(".default")
            }
            baseline = [scenario for scenario in deduped if scenario.id in baseline_ids]
            extras = [scenario for scenario in deduped if scenario.id not in baseline_ids]
            extra_limit = max(0, inputs.max_scenarios_per_module - len(baseline))
            selected = baseline + sorted(extras, key=score_scenario, reverse=True)[:extra_limit]
            for scenario in selected:
                graph.scenarios[scenario.id] = scenario

        return graph

    def _build_candidates(
        self,
        route: RouteInfo,
        view: ViewMetadata | None,
        models: list[ModelMetadata],
        max_choices_per_field: int,
    ) -> list[Scenario]:
        module_id = route.module_id or "core"
        route_key = _route_key(route)
        base = Scenario(
            id=f"{module_id}.{route_key}.default",
            module=module_id,
            route=route.name,
            title="Default",
            goal=f"Show the default state for {route.name}.",
            description=f"Default state for {route.name}",
            params={"route_path": route.pattern},
        )
        scenarios = [base, self._empty_scenario(route)]

        if view and view.is_staff_gated:
            scenarios.append(
                Scenario(
                    id=f"{module_id}.{route_key}.staff",
                    module=module_id,
                    route=route.name,
                    title="Staff View",
                    actor="staff",
                    goal=f"Show the staff-visible state for {route.name}.",
                    description=f"Staff access state for {route.name}",
                    params={"route_path": route.pattern},
                )
            )
            scenarios.append(
                Scenario(
                    id=f"{module_id}.{route_key}.permission_denied",
                    module=module_id,
                    route=route.name,
                    title="Permission Denied",
                    actor="anonymous",
                    goal=f"Show the unauthorized state for {route.name}.",
                    description=f"Unauthorized access state for {route.name}",
                    params={"route_path": route.pattern},
                )
            )

        for model in models:
            if _model_matches_module(model.label, module_id):
                scenarios.append(self._high_volume_scenario(route, model.label))
                for field in model.fields:
                    if field.choices:
                        for choice in field.choices[:max_choices_per_field]:
                            scenarios.append(
                                Scenario(
                                    id=f"{module_id}.{route_key}.{choice}",
                                    module=module_id,
                                    route=route.name,
                                    title=choice.replace("_", " ").title(),
                                    goal=f"Show {route.name} with {model.label} records in the {choice} state.",
                                    description=f"State derived from {model.label}.{field.name}={choice}",
                                    params={"route_path": route.pattern},
                                    seed=SeedSpec(
                                        models=[
                                            ModelSeed(
                                                model=model.label,
                                                count=3,
                                                fields={field.name: choice},
                                            )
                                        ]
                                    ),
                                )
                            )

        return _dedupe_scenarios(scenarios)

    def _empty_scenario(self, route: RouteInfo) -> Scenario:
        return Scenario(
            id=f"{route.module_id}.{_route_key(route)}.empty",
            module=route.module_id,
            route=route.name,
            title="Empty Dataset",
            goal=f"Show the empty dataset state for {route.name}.",
            description=f"No business data for {route.name}",
            params={"route_path": route.pattern},
            seed=SeedSpec(plan=SeedPlan(models=[])),
        )

    def _high_volume_scenario(self, route: RouteInfo, model_label: str) -> Scenario:
        return Scenario(
            id=f"{route.module_id}.{_route_key(route)}.high_volume",
            module=route.module_id,
            route=route.name,
            title="High Volume",
            goal=f"Show a busy, high-volume state for {route.name}.",
            description=f"Large demo dataset for {route.name}",
            params={"route_path": route.pattern},
            seed=SeedSpec(models=[ModelSeed(model=model_label, count=25)]),
        )


def _dedupe_scenarios(scenarios: list[Scenario]) -> list[Scenario]:
    unique: dict[str, Scenario] = {}
    for scenario in scenarios:
        unique[scenario.id] = scenario
    return list(unique.values())


def _model_matches_module(model_label: str, module_id: str) -> bool:
    app_label, _, model_name = model_label.lower().rpartition(".")
    return module_id.lower() in {model_name, f"{model_name}s", app_label}


def _route_key(route: RouteInfo) -> str:
    raw = route.name or route.pattern
    key = re.sub(r"[^a-z0-9_]+", "_", raw.lower()).strip("_")
    return key or "route"
