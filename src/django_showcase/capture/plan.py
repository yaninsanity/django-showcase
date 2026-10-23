from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CaptureTarget:
    viewport: str
    width: int
    height: int
    output_path: str


@dataclass(slots=True)
class CapturePlan:
    module: str
    scenario: str
    route: str
    route_path: str | None
    actor: str | None
    seed_provider: str
    estimated_objects: int
    captures: list[CaptureTarget] = field(default_factory=list)
    route_source: str = "backend"
    is_get_supported: bool = True
    allowed_methods: tuple[str, ...] = ()
    skipped: bool = False
    skipped_reason: str | None = None
