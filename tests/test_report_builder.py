import json
from pathlib import Path

from django_showcase.capture.plan import CapturePlan
from django_showcase.report.builder import ReportBuilder


def test_report_summary_renders_capture_failure_metrics(tmp_path: Path):
    report_dir = tmp_path / "report"
    plan = CapturePlan(
        module="orders",
        scenario="orders.orders.default",
        route="orders",
        route_path="/orders/",
        actor=None,
        seed_provider="existing",
        estimated_objects=0,
        captures=[],
    )
    manifest = {
        "frontend": {
            "framework": "django-mvt",
            "profile": "django-mvt",
            "routes": 0,
            "router_files": [],
            "components": 0,
        },
        "capture": {
            "backend": "playwright",
            "login_failed_pages": 2,
            "login_failed_details": [
                {
                    "scenario": "about.about.default",
                    "route": "about",
                    "reason": "failed (error element)",
                }
            ],
            "fallback_pages": 3,
            "fallback_details": [
                {
                    "scenario": "album.album.default",
                    "route": "album",
                    "reason": "timeout",
                }
            ],
            "issue_skipped_pages": 1,
            "issue_skipped_details": [
                {
                    "scenario": "family_menu.family_menu.default",
                    "route": "family_menu",
                    "reason": "404 not found",
                }
            ],
        },
        "modules": [{"module": "orders", "selected": 1, "candidates": 1}],
        "warnings": [],
    }

    output = ReportBuilder().build(report_dir, [plan], manifest=manifest)

    html = output.read_text(encoding="utf-8")
    assert "Login Failed Pages:" in html
    assert "Login Failed Pages:</strong> 2" in html
    assert "<li>about.about.default (about): failed (error element)</li>" in html
    assert "Fallback Pages:" in html
    assert "Fallback Pages:</strong> 3" in html
    assert "<li>album.album.default (album): timeout</li>" in html
    assert "Issue Skipped Details:" in html
    assert "<strong>404 not found:</strong> 1" in html
    assert "<li>family_menu.family_menu.default (family_menu)</li>" in html