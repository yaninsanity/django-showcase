"""Validation for agent-extracted frontend routes."""
from __future__ import annotations

import json

from django.core.exceptions import ValidationError

from django_showcase.discovery.frontend import FrontendRoute, route_from_path


def parse_frontend_routes(raw: str) -> list[FrontendRoute]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError("Agent route response is not valid JSON.") from exc
    routes: list[FrontendRoute] = []
    for item in data.get("routes", []):
        path = str(item.get("path", ""))
        if not path.startswith("/") or "*" in path or ":" in path:
            continue
        routes.append(route_from_path(path))
    return routes
