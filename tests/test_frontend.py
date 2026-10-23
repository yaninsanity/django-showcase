import json

import pytest
from django.core.exceptions import ValidationError

from django_showcase.agent.frontend import parse_frontend_routes
from django_showcase.discovery.frontend import detect_frontend, detect_frontends


def test_detect_react_and_scan_routes(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "routes.tsx").write_text(
        (
            'const routes = [{path: "/orders"}, {path: "/dashboard"}, '
            '{path: "/orders/:id"}, {path: "*"}]'
        )
    )
    (src / "OrdersPage.tsx").write_text(
        "export default function OrdersPage() { return null; }"
    )

    info = detect_frontend(tmp_path)

    assert info.framework == "react"
    assert info.profile is not None
    assert info.profile.name == "react"
    assert {route.path for route in info.routes} == {"/orders", "/dashboard"}
    assert {route.module for route in info.routes} == {"orders", "dashboard"}
    assert info.router_files == ["src/routes.tsx"]
    assert any(component.name == "OrdersPage" for component in info.components)
    assert any(route.source_file == "src/routes.tsx" for route in info.routes)


def test_detect_mvt_without_package_json(tmp_path):
    info = detect_frontend(tmp_path)
    assert info.framework == "django-mvt"
    assert info.profile is not None
    assert info.profile.name == "django-mvt"
    assert info.routes == []


def test_detect_vue_uses_vue_router_signals(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"vue": "^3.0.0"}})
    )
    src = tmp_path / "src"
    src.mkdir()
    (src / "router.ts").write_text(
        (
            'import { createRouter, createWebHistory } from "vue-router";\n'
            "export const router = createRouter({ history: createWebHistory(), "
            'routes: [{ path: "/customers" }] });'
        )
    )
    (src / "views").mkdir()
    (src / "views" / "CustomersView.vue").write_text(
        "<script setup>const x = 1</script>"
    )

    info = detect_frontend(tmp_path)

    assert info.framework == "vue"
    assert info.profile is not None
    assert info.profile.name == "vue"
    assert info.router_files == ["src/router.ts"]
    assert {route.path for route in info.routes} == {"/customers"}
    assert any(
        component.file_path == "src/views/CustomersView.vue"
        for component in info.components
    )


def test_detect_angular_uses_routing_files(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"dependencies": {"@angular/core": "^19.0.0"}})
    )
    src = tmp_path / "src" / "app"
    src.mkdir(parents=True)
    (src / "app-routing.module.ts").write_text(
        'import { RouterModule, Routes } from "@angular/router";\n'
        'const routes: Routes = [{ path: "orders", component: OrdersPageComponent }];'
    )
    (src / "features").mkdir()
    (src / "features" / "OrdersPageComponent.ts").write_text(
        "export class OrdersPageComponent {}"
    )

    info = detect_frontend(tmp_path)

    assert info.framework == "angular"
    assert info.profile is not None
    assert info.profile.name == "angular"
    assert info.router_files == ["src/app/app-routing.module.ts"]


def test_parse_frontend_routes_filters_unsafe_paths():
    raw = json.dumps(
        {
            "routes": [
                {"path": "/billing"},
                {"path": "javascript:alert(1)"},
                {"path": "/x/:id"},
                {"path": "*"},
            ]
        }
    )
    routes = parse_frontend_routes(raw)
    assert [route.path for route in routes] == ["/billing"]


def test_parse_frontend_routes_rejects_non_json():
    with pytest.raises(ValidationError):
        parse_frontend_routes("<script>alert(1)</script>")


def test_detect_frontends_merges_parallel_roots(tmp_path):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    backend.mkdir()
    frontend.mkdir()
    (backend / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    (frontend / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    (backend / "src").mkdir(parents=True)
    (frontend / "src").mkdir(parents=True)
    (backend / "src" / "routes.tsx").write_text('const routes = [{path: "/dashboard"}]')
    (frontend / "src" / "routes.tsx").write_text('const routes = [{path: "/orders"}]')

    info = detect_frontends([backend, frontend])

    assert info.framework == "react"
    assert {route.path for route in info.routes} == {"/dashboard", "/orders"}
    assert len(info.roots) == 2
