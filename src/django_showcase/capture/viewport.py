from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Viewport:
    id: str
    width: int
    height: int


DESKTOP = Viewport(id="desktop", width=1440, height=1024)
MOBILE = Viewport(id="mobile", width=390, height=844)
