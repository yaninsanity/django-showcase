from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from django_showcase.capture.plan import CapturePlan
from django_showcase.discovery.frontend import FrontendInfo
from django_showcase.discovery.project import ProjectContext
from django_showcase.scenario.scenario import Scenario


@dataclass(slots=True)
class ManifestScenario:
    scenario: str
    module: str
    title: str
    route: str
    actor: str | None
    goal: str | None
    seed_provider: str
    estimated_objects: int
    captures: list[dict[str, object]] = field(default_factory=list)
    status: str = "planned"


def write_manifest(
    path: Path,
    plans: list[CapturePlan],
    context: ProjectContext | None = None,
    frontend: FrontendInfo | None = None,
    scenarios: dict[str, Scenario] | None = None,
    module_candidate_counts: dict[str, int] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    payload = {
        "project": context.project_name if context else None,
        "frontend": {
            "framework": frontend.framework,
            "profile": frontend.profile.name
            if frontend.profile
            else frontend.framework,
            "roots": frontend.roots,
            "routes": len(frontend.routes),
            "router_files": frontend.router_files,
            "components": len(frontend.components),
            "component_files": [
                component.file_path for component in frontend.components
            ],
        }
        if frontend
        else None,
        "modules": [
            {
                "module": module,
                "selected": sum(1 for plan in plans if plan.module == module),
                "candidates": (module_candidate_counts or {}).get(module, 0),
            }
            for module in sorted({plan.module for plan in plans})
        ],
        "warnings": warnings or [],
        "capture": {
            "backend": "unknown",
            "artifacts": sum(len(plan.captures) for plan in plans),
        },
        "scenarios": [
            asdict(
                ManifestScenario(
                    scenario=plan.scenario,
                    module=plan.module,
                    title=(scenarios or {}).get(plan.scenario).title
                    if scenarios
                    else plan.scenario,
                    route=plan.route,
                    actor=plan.actor,
                    goal=(scenarios or {}).get(plan.scenario).goal
                    if scenarios
                    else None,
                    seed_provider=plan.seed_provider,
                    estimated_objects=plan.estimated_objects,
                    captures=[asdict(target) for target in plan.captures],
                )
            )
            for plan in plans
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload
