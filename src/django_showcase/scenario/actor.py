from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class Actor:
    id: str
    permissions: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    attributes: dict[str, object] = field(default_factory=dict)
