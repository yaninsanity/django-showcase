from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from django.urls import URLPattern, URLResolver, get_resolver


@dataclass(slots=True)
class RouteInfo:
    name: str
    pattern: str
    module_id: str
    view_name: str


def discover_routes() -> list[RouteInfo]:
    resolver = get_resolver()
    return list(_flatten_patterns(resolver.url_patterns))


def _flatten_patterns(patterns: Iterable[URLPattern | URLResolver], prefix: str = "") -> Iterable[RouteInfo]:
    for entry in patterns:
        current_pattern = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from _flatten_patterns(entry.url_patterns, current_pattern)
            continue

        route_name = entry.name or _unnamed_route_name(current_pattern)

        module_id = _derive_module_id(route_name, current_pattern)
        callback = entry.callback
        view_name = getattr(callback, "view_class", callback).__name__
        yield RouteInfo(
            name=route_name,
            pattern="/" + current_pattern.lstrip("/"),
            module_id=module_id or "core",
            view_name=view_name,
        )


def _derive_module_id(route_name: str, pattern: str) -> str:
    parts = [part for part in pattern.split("/") if part and "<" not in part]
    first_segment = re.sub(r"[^a-z0-9_]+", "", parts[0].lower()) if parts else ""
    name_module = route_name.split(":")[-1].split("-")[0].split("_")[0]
    clean_name_module = re.sub(r"[^a-z0-9_]+", "", name_module.lower())
    if first_segment in {"admin", "settings", "config", "configuration"}:
        return first_segment
    return clean_name_module or first_segment or "core"


def _unnamed_route_name(pattern: str) -> str:
    clean = re.sub(r"[^a-z0-9_]+", "_", pattern.lower()).strip("_")
    return f"unnamed_{clean or 'route'}"
