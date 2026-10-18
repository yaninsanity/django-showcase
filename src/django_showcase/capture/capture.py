from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from django_showcase.capture.plan import CapturePlan

_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO2p"
    "9e8AAAAASUVORK5CYII="
)


@dataclass(slots=True)
class CaptureResult:
    created_paths: list[str] = field(default_factory=list)
    backend_used: str = "placeholder"
    warnings: list[str] = field(default_factory=list)


class CaptureEngine:
    def __init__(
        self,
        backend: Literal["auto", "playwright", "placeholder"] = "auto",
        base_url: str | None = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self.backend = backend
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds

    def execute(self, plan: CapturePlan, output_dir: Path) -> CaptureResult:
        if self.backend == "placeholder":
            return self._execute_placeholder(plan, output_dir)
        if self.backend == "playwright":
            return self._execute_playwright(plan, output_dir)

        if self.base_url:
            result = self._execute_playwright(plan, output_dir)
            if result.backend_used == "playwright":
                return result
            fallback = self._execute_placeholder(plan, output_dir)
            fallback.warnings.extend(result.warnings)
            return fallback
        return self._execute_placeholder(plan, output_dir)

    def _execute_placeholder(
        self, plan: CapturePlan, output_dir: Path
    ) -> CaptureResult:
        created: list[str] = []
        for target in plan.captures:
            target_path = output_dir / target.output_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(_MINIMAL_PNG)
            meta_path = target_path.with_suffix(".txt")
            meta_path.write_text(
                f"Placeholder capture for {plan.scenario} ({target.viewport})\n"
                f"Route: {plan.route}\n"
                f"Route path: {plan.route_path or '-'}\n"
                f"Actor: {plan.actor or 'default'}\n",
                encoding="utf-8",
            )
            created.append(str(target_path))
        return CaptureResult(created_paths=created, backend_used="placeholder")

    def _execute_playwright(self, plan: CapturePlan, output_dir: Path) -> CaptureResult:
        if not self.base_url:
            return CaptureResult(
                backend_used="placeholder",
                warnings=["CAPTURE_BASE_URL is not set; using placeholder captures."],
            )
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return CaptureResult(
                backend_used="placeholder",
                warnings=[
                    f"Playwright unavailable; using placeholder captures ({exc})."
                ],
            )

        created: list[str] = []
        warnings: list[str] = []
        target_url = self._resolve_url(plan)
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                page.set_default_timeout(int(self.timeout_seconds * 1000))
                for target in plan.captures:
                    page.set_viewport_size(
                        {"width": target.width, "height": target.height}
                    )
                    page.goto(target_url, wait_until="networkidle")
                    target_path = output_dir / target.output_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(target_path), full_page=True)
                    created.append(str(target_path))
                browser.close()
        except Exception as exc:
            warnings.append(
                f"Playwright capture failed; using placeholder captures ({exc})."
            )
            fallback = self._execute_placeholder(plan, output_dir)
            fallback.warnings.extend(warnings)
            return fallback

        return CaptureResult(
            created_paths=created, backend_used="playwright", warnings=warnings
        )

    def _resolve_url(self, plan: CapturePlan) -> str:
        base = (self.base_url or "").rstrip("/")
        route_path = plan.route_path or plan.route
        if route_path.startswith("http://") or route_path.startswith("https://"):
            return route_path
        if not route_path.startswith("/"):
            route_path = "/" + route_path
        return base + route_path
