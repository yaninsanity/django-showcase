import json
from io import StringIO
from pathlib import Path

from django.core.management import call_command


def test_showcase_command_writes_manifest_and_report(settings, tmp_path: Path):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase"}

    call_command("showcase", desktop=True)

    assert (tmp_path / ".showcase" / "manifest.json").exists()
    assert (tmp_path / ".showcase" / "report" / "index.html").exists()
    order_shots = list(
        (tmp_path / ".showcase" / "screenshots" / "backend" / "orders").glob("*.png")
    )
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
    assert "login_failed_pages" in manifest["capture"]
    assert "fallback_pages" in manifest["capture"]
    assert "issue_skipped_pages" in manifest["capture"]
    assert "issue_skipped_by_reason" in manifest["capture"]
    assert "login_failed_details" in manifest["capture"]
    assert "fallback_details" in manifest["capture"]
    assert "issue_skipped_details" in manifest["capture"]
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
    assert all(
        scenario["route"].startswith("billing") for scenario in manifest["scenarios"]
    )


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


def test_showcase_scenario_mode_forces_single_worker(settings, tmp_path: Path, db):
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
        "SCENARIO_MODE": True,
        "CAPTURE_WORKERS": 4,
    }
    stdout = StringIO()

    call_command("showcase", desktop=True, stdout=stdout)

    output = stdout.getvalue()
    assert "forcing CAPTURE_WORKERS=1" in output


def test_showcase_non_scenario_mode_collapses_duplicate_route_scenarios(
    settings, tmp_path: Path
):
    settings.SHOWCASE = {"OUTPUT_DIR": tmp_path / ".showcase", "SCENARIO_MODE": False}
    stdout = StringIO()

    call_command("showcase", desktop=True, log=True, stdout=stdout)

    output = stdout.getvalue()
    assert "collapsing duplicate scenario captures per URL" in output
    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    scenarios = [entry for entry in manifest["scenarios"] if entry["route"] == "orders"]
    assert len(scenarios) == 1


def test_showcase_parallel_capture_logs_when_workers_gt_one(
    settings, tmp_path: Path, monkeypatch
):
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
        "SCENARIO_MODE": False,
        "CAPTURE_WORKERS": 3,
    }
    stdout = StringIO()

    class FakeFuture:
        def __init__(self, value):
            self._value = value

        def result(self):
            return self._value

    class FakeExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            return FakeFuture(fn(*args, **kwargs))

    monkeypatch.setattr(
        "django_showcase.management.commands.showcase.ThreadPoolExecutor",
        FakeExecutor,
    )
    monkeypatch.setattr(
        "django_showcase.management.commands.showcase.as_completed",
        lambda futures: futures,
    )

    call_command("showcase", desktop=True, log=True, stdout=stdout)

    output = stdout.getvalue()
    assert "capture mode=parallel route_source=backend workers=3" in output
    assert "parallel capture submitted tasks=" in output
    assert "parallel capture progress completed=" in output


def test_showcase_frontend_runs_sequential_even_when_backend_parallel(
    settings, tmp_path: Path
):
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
        "CAPTURE_WORKERS": 3,
        "SCENARIO_MODE": False,
    }
    stdout = StringIO()

    call_command("showcase", desktop=True, log=True, stdout=stdout)

    output = stdout.getvalue()
    assert "capture mode=parallel route_source=backend workers=3" in output
    assert "capture mode=sequential route_source=frontend workers=1" in output


def test_showcase_uses_default_engine_login_retry_settings(
    settings, tmp_path: Path, monkeypatch
):
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
    }
    observed: dict[str, object] = {}

    class FakeCaptureEngine:
        def __init__(self, **kwargs):
            observed.update(kwargs)

        def prepare_auth_user(self):
            return True

        def execute(self, *_args, **_kwargs):
            return type(
                "Result",
                (),
                {
                    "backend_used": "placeholder",
                    "warnings": [],
                    "skipped": False,
                    "skipped_reason": None,
                    "created_paths": [],
                    "login_failed": False,
                    "fallback_used": False,
                },
            )()

        def cleanup_temp_user(self):
            return None

    monkeypatch.setattr(
        "django_showcase.management.commands.showcase.CaptureEngine",
        FakeCaptureEngine,
    )

    call_command("showcase", desktop=True)

    assert "login_retry_attempts" not in observed
    assert "login_retry_delay_seconds" not in observed


def test_showcase_deferred_retry_success_cleans_failure_artifacts(
    settings, tmp_path: Path, monkeypatch
):
    settings.SHOWCASE = {
        "OUTPUT_DIR": tmp_path / ".showcase",
        "SCENARIO_MODE": False,
        "CAPTURE_WORKERS": 2,
    }

    class FakeFuture:
        def __init__(self, value):
            self._value = value

        def result(self):
            return self._value

    class FakeExecutor:
        def __init__(self, max_workers):
            self.max_workers = max_workers

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, fn, *args, **kwargs):
            return FakeFuture(fn(*args, **kwargs))

    monkeypatch.setattr(
        "django_showcase.management.commands.showcase.ThreadPoolExecutor",
        FakeExecutor,
    )
    monkeypatch.setattr(
        "django_showcase.management.commands.showcase.as_completed",
        lambda futures: futures,
    )

    class FakeCaptureEngine:
        def __init__(self, **_kwargs):
            self.calls_by_scenario: dict[str, int] = {}

        def prepare_auth_user(self):
            return True

        def execute(self, plan, output_dir):
            count = self.calls_by_scenario.get(plan.scenario, 0) + 1
            self.calls_by_scenario[plan.scenario] = count
            target = plan.captures[0]
            screenshot = output_dir / target.output_path
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            placeholder_txt = screenshot.with_suffix(".txt")
            skip_txt = (output_dir.parent / "skipped" / target.output_path).with_suffix(
                ".txt"
            )

            if count == 1:
                skip_txt.parent.mkdir(parents=True, exist_ok=True)
                screenshot.write_bytes(b"placeholder")
                placeholder_txt.write_text("placeholder", encoding="utf-8")
                skip_txt.write_text("skip", encoding="utf-8")
                return type(
                    "Result",
                    (),
                    {
                        "backend_used": "playwright",
                        "warnings": [],
                        "skipped": True,
                        "skipped_reason": "non-renderable route",
                        "created_paths": [str(screenshot)],
                        "login_failed": False,
                        "fallback_used": False,
                        "retryable": True,
                    },
                )()

            screenshot.write_bytes(b"real")
            return type(
                "Result",
                (),
                {
                    "backend_used": "playwright",
                    "warnings": [],
                    "skipped": False,
                    "skipped_reason": None,
                    "created_paths": [str(screenshot)],
                    "login_failed": False,
                    "fallback_used": False,
                    "retryable": False,
                },
            )()

        def cleanup_capture_artifacts(self, plan, output_dir):
            target = plan.captures[0]
            screenshot = output_dir / target.output_path
            for path in (screenshot, screenshot.with_suffix(".txt")):
                if path.exists():
                    path.unlink()
            skip_txt = (output_dir.parent / "skipped" / target.output_path).with_suffix(
                ".txt"
            )
            if skip_txt.exists():
                skip_txt.unlink()
            parent = skip_txt.parent
            skipped_root = output_dir.parent / "skipped"
            while parent != skipped_root:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
            try:
                skipped_root.rmdir()
            except OSError:
                pass

        def cleanup_temp_user(self):
            return None

    monkeypatch.setattr(
        "django_showcase.management.commands.showcase.CaptureEngine",
        FakeCaptureEngine,
    )

    call_command("showcase", desktop=True)

    manifest = json.loads((tmp_path / ".showcase" / "manifest.json").read_text())
    assert manifest["capture"]["issue_skipped_pages"] == 0
    screenshots = list((tmp_path / ".showcase" / "screenshots").rglob("*.png"))
    assert screenshots
    assert (tmp_path / ".showcase" / "skipped").exists() is False
