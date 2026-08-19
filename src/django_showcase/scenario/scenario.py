from __future__ import annotations

from dataclasses import dataclass, field

from django_showcase.seed.plan import SeedSpec


@dataclass(slots=True)
class CaptureSpec:
    desktop: bool = True
    mobile: bool = True


@dataclass(slots=True)
class Scenario:
    id: str
    module: str
    route: str
    title: str
    description: str | None = None
    goal: str | None = None
    actor: str | None = None
    params: dict[str, object] = field(default_factory=dict)
    seed: SeedSpec | None = None
    setup: list[str] = field(default_factory=list)
    capture: CaptureSpec = field(default_factory=CaptureSpec)
