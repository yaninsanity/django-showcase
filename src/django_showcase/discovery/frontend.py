"""Deterministic frontend framework detection and route scanning."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

_SOURCE_SUFFIXES = {".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte"}
_ROUTE_RE = re.compile(r"""path\s*[:=]\s*["']([^"']*)["']""")
_ROUTER_SIGNAL_RE = re.compile(r"useRoutes|createBrowserRouter|Routes|Route|router|routes", re.IGNORECASE)
_COMPONENT_NAME_RE = re.compile(r"(?:export\s+default\s+function|function|const)\s+([A-Z][A-Za-z0-9_]*)")
_MAX_FILES = 400
_FRAMEWORK_DEPS = {"react": "react", "vue": "vue", "svelte": "svelte", "@angular/core": "angular"}
_ROUTER_FILE_HINTS = ("route", "router", "routes", "navigation", "app")


@dataclass(frozen=True, slots=True)
class FrontendProfile:
    name: str
    router_file_hints: tuple[str, ...]
    router_signals: tuple[str, ...]
    component_dir_hints: tuple[str, ...]


FRONTEND_PROFILES: dict[str, FrontendProfile] = {
    "django-mvt": FrontendProfile(
        name="django-mvt",
        router_file_hints=(),
        router_signals=(),
        component_dir_hints=(),
    ),
    "react": FrontendProfile(
        name="react",
        router_file_hints=("route", "router", "routes", "navigation", "app"),
        router_signals=("useRoutes", "createBrowserRouter", "Routes", "Route"),
        component_dir_hints=("components", "pages", "screens"),
    ),
    "vue": FrontendProfile(
        name="vue",
        router_file_hints=("router", "routes", "route", "app"),
        router_signals=("createRouter", "createWebHistory", "RouterView", "routes"),
        component_dir_hints=("components", "views", "pages"),
    ),
    "svelte": FrontendProfile(
        name="svelte",
        router_file_hints=("routes", "route", "router", "+page"),
        router_signals=("+page", "load", "goto", "routes"),
        component_dir_hints=("routes", "components", "lib"),
    ),
    "angular": FrontendProfile(
        name="angular",
        router_file_hints=("routing", "routes", "router", "app"),
        router_signals=("RouterModule", "provideRouter", "loadChildren", "Routes"),
        component_dir_hints=("components", "pages", "features"),
    ),
    "node": FrontendProfile(
        name="node",
        router_file_hints=_ROUTER_FILE_HINTS,
        router_signals=("router", "routes", "path"),
        component_dir_hints=("components", "pages", "views"),
    ),
}


@dataclass(slots=True)
class FrontendRoute:
    path: str
    module: str
    title: str
    source_file: str | None = None


@dataclass(slots=True)
class FrontendComponent:
    id: str
    name: str
    module: str
    file_path: str


@dataclass(slots=True)
class FrontendInfo:
    framework: str
    profile: FrontendProfile | None = None
    roots: list[str] = field(default_factory=list)
    routes: list[FrontendRoute] = field(default_factory=list)
    router_files: list[str] = field(default_factory=list)
    components: list[FrontendComponent] = field(default_factory=list)


def detect_frontend(root: Path) -> FrontendInfo:
    framework = _detect_framework(root)
    profile = FRONTEND_PROFILES[framework]
    if framework == "django-mvt":
        return FrontendInfo(framework=framework, profile=profile, roots=[str(root)])
    router_files = [str(path.relative_to(root)) for path in scan_router_files(root, profile)]
    return FrontendInfo(
        framework=framework,
        profile=profile,
        roots=[str(root)],
        routes=scan_frontend_routes(root, profile),
        router_files=router_files,
        components=scan_frontend_components(root, profile),
    )


def detect_frontends(roots: list[Path]) -> FrontendInfo:
    infos = [detect_frontend(root) for root in roots if root.exists()]
    if not infos:
        return FrontendInfo(framework="django-mvt", profile=FRONTEND_PROFILES["django-mvt"])

    framework = _pick_framework(infos)
    profile = FRONTEND_PROFILES[framework]
    routes: dict[str, FrontendRoute] = {}
    router_files: set[str] = set()
    components: dict[str, FrontendComponent] = {}
    roots_out: list[str] = []

    for info in infos:
        roots_out.extend(info.roots)
        for route in info.routes:
            routes.setdefault(route.path, route)
        router_files.update(info.router_files)
        for component in info.components:
            components.setdefault(component.id, component)

    return FrontendInfo(
        framework=framework,
        profile=profile,
        roots=roots_out,
        routes=list(routes.values()),
        router_files=sorted(router_files),
        components=list(components.values()),
    )


def route_from_path(path: str) -> FrontendRoute:
    clean = "/" + path.strip("/")
    segment = clean.strip("/").split("/")[0]
    module = re.sub(r"[^a-z0-9_]+", "", segment.lower()) or "home"
    return FrontendRoute(path=clean, module=module, title=module.replace("_", " ").title())


def scan_frontend_routes(root: Path, profile: FrontendProfile | None = None) -> list[FrontendRoute]:
    profile = profile or FRONTEND_PROFILES[_detect_framework(root)]
    seen: dict[str, FrontendRoute] = {}
    router_files = scan_router_files(root, profile)
    prioritized = list(router_files)
    prioritized.extend(path for path in _iter_sources(root) if path not in router_files)
    for source in prioritized:
        text = source.read_text(encoding="utf-8", errors="ignore")
        for match in _ROUTE_RE.finditer(text):
            raw = match.group(1)
            if not raw.startswith("/") or "*" in raw or ":" in raw:
                continue
            route = route_from_path(raw)
            route.source_file = str(source.relative_to(root))
            seen.setdefault(route.path, route)
    return list(seen.values())


def scan_router_files(root: Path, profile: FrontendProfile | None = None) -> list[Path]:
    profile = profile or FRONTEND_PROFILES[_detect_framework(root)]
    matches: list[Path] = []
    for source in _iter_sources(root):
        name = source.name.lower()
        text = source.read_text(encoding="utf-8", errors="ignore")
        if any(hint in name for hint in profile.router_file_hints) or any(
            signal in text for signal in profile.router_signals
        ) or _ROUTER_SIGNAL_RE.search(text):
            matches.append(source)
    return matches


def scan_frontend_components(root: Path, profile: FrontendProfile | None = None) -> list[FrontendComponent]:
    profile = profile or FRONTEND_PROFILES[_detect_framework(root)]
    components: dict[str, FrontendComponent] = {}
    for source in _iter_sources(root):
        if profile.component_dir_hints and not any(
            hint in part.lower() for part in source.parts for hint in profile.component_dir_hints
        ) and not source.stem[:1].isupper():
            continue
        text = source.read_text(encoding="utf-8", errors="ignore")
        names = {match.group(1) for match in _COMPONENT_NAME_RE.finditer(text)}
        if not names and source.stem[:1].isupper():
            names.add(source.stem)
        for name in names:
            module = _module_from_file(source)
            component = FrontendComponent(
                id=f"{module}.{name.lower()}",
                name=name,
                module=module,
                file_path=str(source.relative_to(root)),
            )
            components.setdefault(component.id, component)
    return list(components.values())


def collect_route_snippets(root: Path, limit: int = 8000) -> str:
    chunks: list[str] = []
    total = 0
    profile = FRONTEND_PROFILES[_detect_framework(root)]
    router_files = scan_router_files(root, profile)
    prioritized = list(router_files)
    prioritized.extend(path for path in _iter_sources(root) if path not in router_files)
    for source in prioritized:
        text = source.read_text(encoding="utf-8", errors="ignore")
        if "path" not in text and not _ROUTER_SIGNAL_RE.search(text):
            continue
        chunk = f"// {source.relative_to(root)}\n{text[:1200]}"
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            break
    return "\n\n".join(chunks)


def _detect_framework(root: Path) -> str:
    package_json = root / "package.json"
    if not package_json.exists():
        return "django-mvt"
    try:
        data = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return "node"
    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    for dep, framework in _FRAMEWORK_DEPS.items():
        if dep in deps:
            return framework
    return "node"


def _iter_sources(root: Path) -> Iterator[Path]:
    count = 0
    for path in root.rglob("*"):
        if path.suffix not in _SOURCE_SUFFIXES:
            continue
        if any(part.startswith(".") or part == "node_modules" for part in path.parts):
            continue
        count += 1
        if count > _MAX_FILES:
            return
        yield path


def _module_from_file(path: Path) -> str:
    for part in reversed(path.parts[:-1]):
        clean = re.sub(r"[^a-z0-9_]+", "", part.lower())
        if clean and clean not in {"src", "app", "components", "pages", "views"}:
            return clean
    return re.sub(r"[^a-z0-9_]+", "", path.stem.lower()) or "frontend"


def _pick_framework(infos: list[FrontendInfo]) -> str:
    for preferred in ("react", "vue", "angular", "svelte", "node"):
        if any(info.framework == preferred for info in infos):
            return preferred
    return "django-mvt"
