from __future__ import annotations

from dataclasses import dataclass, field

from .scenario import Scenario


@dataclass(slots=True)
class Module:
    id: str
    title: str
    routes: list[str]


@dataclass(slots=True)
class ScenarioDependency:
    source: str
    target: str
    reason: str


@dataclass(slots=True)
class ScenarioGraph:
    modules: dict[str, Module] = field(default_factory=dict)
    scenarios: dict[str, Scenario] = field(default_factory=dict)
    module_candidate_counts: dict[str, int] = field(default_factory=dict)
    dependencies: list[ScenarioDependency] = field(default_factory=list)
