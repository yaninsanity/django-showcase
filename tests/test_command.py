import json
from pathlib import Path

from django.core.management import call_command


def test_showcase_command_writes_manifest_and_report(settings, tmp_path: Path):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}

    call_command("showcase")

    assert (tmp_path / ".showcase" / "manifest.json").exists()
    assert (tmp_path / ".showcase" / "report" / "index.html").exists()
    assert (
        tmp_path
        / ".showcase"
        / "screenshots"
        / "orders"
        / "orders__orders__pending"
        / "desktop.png"
    ).exists()
    assert (tmp_path / ".showcase" / "showcase.zip").exists()


def test_showcase_manifest_includes_frontend_summary(settings, tmp_path: Path):
    frontend_dir = tmp_path / "frontend"
    src = frontend_dir / "src"
    src.mkdir(parents=True)
    (frontend_dir / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    (src / "appRoutes.tsx").write_text('const routes = [{path: "/billing"}]')
    (src / "BillingPage.tsx").write_text(
        "export default function BillingPage() { return null; }"
    )
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
        "FRONTEND_DIR": frontend_dir,
    }

    call_command("showcase")

    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    assert manifest["frontend"]["framework"] == "react"
    assert manifest["frontend"]["roots"]
    assert manifest["frontend"]["routes"] == 1
    assert manifest["frontend"]["components"] >= 1
    assert manifest["frontend"]["router_files"] == ["src/appRoutes.tsx"]
    assert manifest["capture"]["backend"] in {
        "placeholder",
        "playwright",
        "playwright+placeholder",
    }
    assert manifest["frontend"]["profile"] == "react"
    assert any(module["module"] == "billing" for module in manifest["modules"])


def test_showcase_supports_parallel_frontend_dirs(settings, tmp_path: Path):
    backend_ui = tmp_path / "backend_ui"
    frontend_ui = tmp_path / "frontend_ui"
    (backend_ui / "src").mkdir(parents=True)
    (frontend_ui / "src").mkdir(parents=True)
    (backend_ui / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    (frontend_ui / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    (backend_ui / "src" / "appRoutes.tsx").write_text(
        'const routes = [{path: "/dashboard"}]'
    )
    (frontend_ui / "src" / "appRoutes.tsx").write_text(
        'const routes = [{path: "/customers"}]'
    )
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
        "FRONTEND_DIR": backend_ui,
        "FRONTEND_DIRS": [str(frontend_ui)],
    }

    call_command("showcase")

    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    assert manifest["frontend"]["routes"] == 2
