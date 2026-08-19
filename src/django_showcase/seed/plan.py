from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ModelSeed:
    model: str
    count: int = 1
    fields: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class ActorSeed:
    actor_id: str
    attributes: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class RelationshipSeed:
    source: str
    target: str


@dataclass(slots=True)
class SeedAssertion:
    message: str


@dataclass(slots=True)
class SeedPlan:
    models: list[ModelSeed] = field(default_factory=list)
    actor: ActorSeed | None = None
    relationships: list[RelationshipSeed] = field(default_factory=list)
    assertions: list[SeedAssertion] = field(default_factory=list)


@dataclass(slots=True)
class SeedSpec:
    models: list[ModelSeed] = field(default_factory=list)
    plan: SeedPlan | None = None

    def compile(self) -> SeedPlan:
        if self.plan is not None:
            return self.plan
        return SeedPlan(models=list(self.models))
