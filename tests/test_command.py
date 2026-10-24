import json
from io import StringIO
from pathlib import Path

from django.core.management import call_command


def test_showcase_command_writes_manifest_and_report(settings, tmp_path: Path):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}

    call_command("showcase", desktop=True)

    assert (tmp_path / ".showcase" / "manifest.json").exists()
    assert (tmp_path / ".showcase" / "report" / "index.html").exists()
    order_shots = list((tmp_path / ".showcase" / "screenshots" / "backend" / "orders").glob("*.png"))
    assert order_shots
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

    call_command("showcase", desktop=True)

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
        "placeholder+skipped",
        "playwright+skipped",
        "playwright+placeholder+skipped",
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

    call_command("showcase", desktop=True)

    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    assert manifest["frontend"]["routes"] == 2


def test_showcase_log_flag_prints_capture_events(settings, tmp_path: Path):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}
    stdout = StringIO()

    call_command("showcase", desktop=True, log=True, stdout=stdout)

    output = stdout.getvalue()
    assert "[capture]" in output
    assert "fallback placeholder" in output


def test_showcase_skip_excludes_admin_module(settings, tmp_path: Path):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}

    call_command("showcase", plan=True, desktop=True, skip=["admin"])

    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    assert all(module["module"] != "admin" for module in manifest["modules"])
    assert all(scenario["module"] != "admin" for scenario in manifest["scenarios"])


def test_showcase_only_and_skip_can_be_combined(settings, tmp_path: Path):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}

    call_command(
        "showcase",
        plan=True,
        desktop=True,
        only=["orders", "admin"],
        skip=["admin"],
    )

    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    modules = {module["module"] for module in manifest["modules"]}
    assert "admin" not in modules
    assert modules <= {"orders"}


def test_showcase_frontend_only_filters_backend_routes(settings, tmp_path: Path):
    frontend_dir = tmp_path / "frontend"
    src = frontend_dir / "src"
    src.mkdir(parents=True)
    (frontend_dir / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    (src / "appRoutes.tsx").write_text('const routes = [{path: "/billing"}]')
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
        "FRONTEND_DIR": frontend_dir,
    }

    call_command("showcase", plan=True, desktop=True, frontend=True)

    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    assert manifest["scenarios"]
    assert all(scenario["route"].startswith("billing") for scenario in manifest["scenarios"])


def test_showcase_backend_only_filters_frontend_routes(settings, tmp_path: Path):
    frontend_dir = tmp_path / "frontend"
    src = frontend_dir / "src"
    src.mkdir(parents=True)
    (frontend_dir / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    (src / "appRoutes.tsx").write_text('const routes = [{path: "/billing"}]')
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
        "FRONTEND_DIR": frontend_dir,
    }

    call_command("showcase", plan=True, desktop=True, backend=True)

    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    assert all(scenario["module"] != "billing" for scenario in manifest["scenarios"])


def test_showcase_screenshots_split_by_source_when_mixed(settings, tmp_path: Path):
    frontend_dir = tmp_path / "frontend"
    src = frontend_dir / "src"
    src.mkdir(parents=True)
    (frontend_dir / "package.json").write_text(
        json.dumps({"dependencies": {"react": "^18.0.0"}})
    )
    (src / "appRoutes.tsx").write_text('const routes = [{path: "/billing"}]')
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
        "FRONTEND_DIR": frontend_dir,
    }

    call_command("showcase", desktop=True, mobile=True)

    assert (tmp_path / ".showcase" / "screenshots" / "desktop" / "backend").exists()
    assert (tmp_path / ".showcase" / "screenshots" / "desktop" / "frontend").exists()
    assert (tmp_path / ".showcase" / "screenshots" / "mobile" / "backend").exists()
    assert (tmp_path / ".showcase" / "screenshots" / "mobile" / "frontend").exists()


def test_showcase_requires_explicit_device_selection(settings, tmp_path: Path):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}
    stdout = StringIO()

    call_command("showcase", stdout=stdout)

    output = stdout.getvalue()
    assert "No device selected" in output
    assert not (tmp_path / ".showcase" / "manifest.json").exists()


def test_showcase_timing_flag_prints_total_duration(settings, tmp_path: Path):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}
    stdout = StringIO()

    call_command("showcase", timing=True, stdout=stdout)

    output = stdout.getvalue()
    assert "Total duration:" in output


def test_showcase_pdf_flag_emits_pdf_message(settings, tmp_path: Path, monkeypatch):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}
    stdout = StringIO()

    from django_showcase.report.builder import ReportBuilder

    monkeypatch.setattr(
        ReportBuilder,
        "build_pdf",
        lambda _self, report_dir, screenshot_paths: report_dir / "screenshots.pdf",
    )

    call_command("showcase", desktop=True, pdf=True, stdout=stdout)

    output = stdout.getvalue()
    assert "PDF report written to" in output
