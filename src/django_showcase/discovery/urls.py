from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

from django.urls import URLPattern, URLResolver, get_resolver


@dataclass(slots=True)
class RouteInfo:
    name: str
    pattern: str
    module_id: str
    view_name: str
    is_get_supported: bool = True
    route_source: str = "backend"
    allowed_methods: tuple[str, ...] = ()


def normalize_route_pattern(pattern: str) -> str:
    raw = str(pattern or "").strip()
    if not raw:
        return "/"

    normalized = raw.replace("\\/", "/").replace("\\.", ".")
    normalized = normalized.replace("^", "").replace("$", "")
    normalized = normalized.replace("/?", "/")

    def replace_group(match: re.Match[str]) -> str:
        group_name = match.group(1).lower()
        return _sample_placeholder(name=group_name)

    normalized = re.sub(
        r"\(\?P<([A-Za-z_][A-Za-z0-9_]*)>[^)]+\)",
        replace_group,
        normalized,
    )
    normalized = re.sub(
        r"<(?:(?P<converter>[a-zA-Z_][a-zA-Z0-9_]*):)?"
        r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)>",
        lambda match: _sample_placeholder(
            converter=(match.group("converter") or "").lower(),
            name=(match.group("name") or "").lower(),
        ),
        normalized,
    )
    normalized = re.sub(r"[\[\]\(\)\{\}\+\?\*\|]", "", normalized)
    normalized = re.sub(r"\\", "/", normalized)
    normalized = re.sub(r"/{2,}", "/", normalized)
    if not normalized.startswith("/"):
        normalized = "/" + normalized.lstrip("/")
    normalized = normalized.rstrip("/")
    if not normalized:
        return "/"
    if normalized in {"/", ""}:
        return "/"
    return normalized if normalized.endswith("/") else normalized + "/"


def discover_routes() -> list[RouteInfo]:
    resolver = get_resolver()
    return list(_flatten_patterns(resolver.url_patterns))


def _flatten_patterns(
    patterns: Iterable[URLPattern | URLResolver], prefix: str = ""
) -> Iterable[RouteInfo]:
    for entry in patterns:
        current_pattern = prefix + str(entry.pattern)
        if isinstance(entry, URLResolver):
            yield from _flatten_patterns(entry.url_patterns, current_pattern)
            continue

        route_name = entry.name or _unnamed_route_name(current_pattern)
        normalized_pattern = normalize_route_pattern(current_pattern)

        module_id = _derive_module_id(route_name, current_pattern)
        callback = entry.callback
        view_name = getattr(callback, "view_class", callback).__name__
        allowed_methods = _allowed_methods(callback)
        yield RouteInfo(
            name=route_name,
            pattern=normalized_pattern,
            module_id=module_id or "core",
            view_name=view_name,
            is_get_supported=_supports_get(allowed_methods),
            route_source="backend",
            allowed_methods=allowed_methods,
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


def _allowed_methods(callback: object) -> tuple[str, ...]:
    actions = getattr(callback, "actions", None)
    if isinstance(actions, dict):
        return tuple(sorted({str(key).lower() for key in actions.keys()}))

    methods = getattr(callback, "methods", None)
    if methods is not None:
        return tuple(sorted({str(method).lower() for method in methods}))

    view_class = getattr(callback, "view_class", None) or getattr(callback, "cls", None)
    if view_class is not None:
        method_names = getattr(view_class, "http_method_names", None)
        if method_names is not None:
            method_set = {
                str(method).lower()
                for method in method_names
                if str(method).lower() != "options"
            }
            return tuple(sorted(method_set))

    return ()


def _supports_get(allowed_methods: tuple[str, ...]) -> bool:
    if not allowed_methods:
        # Keep unknown endpoints for runtime probing.
        return True
    method_set = set(allowed_methods)
    return "get" in method_set or "head" in method_set


def _sample_placeholder(converter: str = "", name: str = "") -> str:
    if name in {"format", "ext", "extension"}:
        return "json"
    if name in {"pk", "id"} or name.endswith("_id"):
        return "1"
    if "uuid" in name or converter == "uuid":
        return "00000000-0000-0000-0000-000000000000"
    if "slug" in name or converter == "slug":
        return "demo"
    if name in {"username", "name"}:
        return "demo"
    if converter in {"int"}:
        return "1"
    if converter in {"path"}:
        return "sample"
    return "value"
