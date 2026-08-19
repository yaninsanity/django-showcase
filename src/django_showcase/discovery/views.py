from __future__ import annotations

from dataclasses import dataclass

from .urls import RouteInfo


@dataclass(slots=True)
class ViewMetadata:
    route_name: str
    view_name: str
    is_staff_gated: bool = False


def inspect_views(routes: list[RouteInfo]) -> list[ViewMetadata]:
    metadata: list[ViewMetadata] = []
    for route in routes:
        lower_name = route.view_name.lower()
        metadata.append(
            ViewMetadata(
                route_name=route.name,
                view_name=route.view_name,
                is_staff_gated="admin" in lower_name or "staff" in lower_name,
            )
        )
    return metadata
