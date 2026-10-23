from __future__ import annotations

from django_showcase.capture.plan import CapturePlan, CaptureTarget
from django_showcase.capture.viewport import DESKTOP, MOBILE
from django_showcase.scenario.graph import ScenarioGraph


class CapturePlanCompiler:
    def compile(self, graph: ScenarioGraph) -> list[CapturePlan]:
        plans: list[CapturePlan] = []
        for scenario in graph.scenarios.values():
            seed_plan = scenario.seed.compile() if scenario.seed else None
            estimated_objects = (
                sum(item.count for item in seed_plan.models) if seed_plan else 0
            )
            output_key = scenario.id.replace(".", "__")
            captures: list[CaptureTarget] = []
            if scenario.capture.desktop:
                captures.append(
                    CaptureTarget(
                        viewport=DESKTOP.id,
                        width=DESKTOP.width,
                        height=DESKTOP.height,
                        output_path=f"{scenario.module}/{output_key}/{DESKTOP.id}.png",
                    )
                )
            if scenario.capture.mobile:
                captures.append(
                    CaptureTarget(
                        viewport=MOBILE.id,
                        width=MOBILE.width,
                        height=MOBILE.height,
                        output_path=f"{scenario.module}/{output_key}/{MOBILE.id}.png",
                    )
                )

            plans.append(
                CapturePlan(
                    module=scenario.module,
                    scenario=scenario.id,
                    route=scenario.route,
                    route_path=scenario.params.get("route_path")
                    if scenario.params
                    else None,
                    actor=scenario.actor,
                    seed_provider="deterministic" if scenario.seed else "existing",
                    estimated_objects=estimated_objects,
                    route_source=(
                        str(scenario.params.get("route_source", "backend"))
                        if scenario.params
                        else "backend"
                    ),
                    is_get_supported=(
                        bool(scenario.params.get("is_get_supported", True))
                        if scenario.params
                        else True
                    ),
                    allowed_methods=(
                        tuple(
                            str(method).lower()
                            for method in scenario.params.get("allowed_methods", [])
                        )
                        if scenario.params
                        else ()
                    ),
                    captures=captures,
                )
            )
        return plans
