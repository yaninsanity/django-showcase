from __future__ import annotations

import re

from django_showcase.capture.plan import CapturePlan, CaptureTarget
from django_showcase.capture.viewport import DESKTOP, MOBILE
from django_showcase.scenario.graph import ScenarioGraph


class CapturePlanCompiler:
    def compile(
        self,
        graph: ScenarioGraph,
        include_desktop: bool = True,
        include_mobile: bool = True,
        split_devices: bool = True,
    ) -> list[CapturePlan]:
        plans: list[CapturePlan] = []
        for scenario in graph.scenarios.values():
            seed_plan = scenario.seed.compile() if scenario.seed else None
            estimated_objects = (
                sum(item.count for item in seed_plan.models) if seed_plan else 0
            )
            output_name = _candidate_output_name(scenario.id, scenario.module)
            captures: list[CaptureTarget] = []
            if include_desktop and scenario.capture.desktop:
                desktop_path = f"{scenario.module}/{output_name}.png"
                if split_devices:
                    desktop_path = f"{DESKTOP.id}/{desktop_path}"
                captures.append(
                    CaptureTarget(
                        viewport=DESKTOP.id,
                        width=DESKTOP.width,
                        height=DESKTOP.height,
                        output_path=desktop_path,
                    )
                )
            if include_mobile and scenario.capture.mobile:
                mobile_path = f"{scenario.module}/{output_name}.png"
                if split_devices:
                    mobile_path = f"{MOBILE.id}/{mobile_path}"
                captures.append(
                    CaptureTarget(
                        viewport=MOBILE.id,
                        width=MOBILE.width,
                        height=MOBILE.height,
                        output_path=mobile_path,
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


def _candidate_output_name(scenario_id: str, module_id: str) -> str:
    prefix = f"{module_id}."
    candidate = scenario_id[len(prefix) :] if scenario_id.startswith(prefix) else scenario_id
    candidate = re.sub(r"[^a-zA-Z0-9_.-]+", "_", candidate).strip("._")
    if not candidate:
        candidate = "scenario"
    return candidate.replace(".", "__")
