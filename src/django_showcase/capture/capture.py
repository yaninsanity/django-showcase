from __future__ import annotations

import base64
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
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
        capture_username: str = "showcaseuser",
        capture_password: str = "showcaseuser",
        cleanup_temp_user: bool = True,
        event_logger: Callable[[str], None] | None = None,
    ) -> None:
        self.backend = backend
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.capture_username = capture_username
        self.capture_password = capture_password
        self.cleanup_temp_user_enabled = cleanup_temp_user
        self._temp_user_created = False
        self._event_logger = event_logger

    def _log(self, message: str) -> None:
        if self._event_logger is not None:
            self._event_logger(message)

    def execute(self, plan: CapturePlan, output_dir: Path) -> CaptureResult:
        if self.backend == "placeholder":
            return self._execute_placeholder(
                plan,
                output_dir,
                reason="backend=placeholder",
            )
        if self.backend == "playwright":
            return self._execute_playwright(plan, output_dir)

        if self.base_url:
            result = self._execute_playwright(plan, output_dir)
            if result.backend_used == "playwright":
                return result
            fallback = self._execute_placeholder(
                plan,
                output_dir,
                reason=f"auto fallback after playwright failure: {result.warnings}",
            )
            fallback.warnings.extend(result.warnings)
            return fallback
        return self._execute_placeholder(
            plan,
            output_dir,
            reason="CAPTURE_BASE_URL is not set; placeholder is active",
        )

    def _execute_placeholder(
        self,
        plan: CapturePlan,
        output_dir: Path,
        reason: str = "placeholder backend",
    ) -> CaptureResult:
        self._log(
            f"fallback placeholder for scenario={plan.scenario} route={plan.route}: {reason}"
        )
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
                f"Route URL: {self._resolve_url(plan)}\n"
                f"Actor: {plan.actor or 'default'}\n"
                f"Backend: {self.backend}\n"
                f"Base URL: {self.base_url or '-'}\n"
                f"Reason: {reason}\n",
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
        if not self._ensure_playwright_runtime():
            return CaptureResult(
                backend_used="placeholder",
                warnings=[
                    "Playwright runtime installation failed; using placeholder captures."
                ],
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
        user_ready = self._ensure_django_superuser()
        if not user_ready:
            self._log(
                f"temp user ensure failed before capture for scenario={plan.scenario}; login may fail"
            )
        self._log(f"capture start scenario={plan.scenario} url={target_url}")
        try:
            with sync_playwright() as playwright:
                browser = self._launch_playwright_browser(playwright)
                context = browser.new_context()
                page = context.new_page()
                page.set_default_timeout(int(self.timeout_seconds * 1000))
                for target in plan.captures:
                    page.set_viewport_size(
                        {"width": target.width, "height": target.height}
                    )
                    page.goto(target_url, wait_until="networkidle")
                    logged_in = self._login_if_needed(page)
                    if logged_in:
                        self._log(
                            f"login submitted for scenario={plan.scenario} user={self.capture_username}"
                        )
                        login_result = self._diagnose_login_result(page)
                        if login_result:
                            self._log(
                                f"login status for scenario={plan.scenario}: {login_result}"
                            )
                    if page.url != target_url:
                        page.goto(target_url, wait_until="networkidle")
                    target_path = output_dir / target.output_path
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(target_path), full_page=True)
                    created.append(str(target_path))
                    self._log(
                        f"capture success scenario={plan.scenario} viewport={target.viewport} output={target.output_path}"
                    )
                context.close()
                browser.close()
        except Exception as exc:
            reason = (
                f"Playwright capture failed for route {target_url}: {exc}. "
                "Browser launch, login, or navigation may have failed."
            )
            warnings.append(
                f"Playwright capture failed; using placeholder captures ({exc})."
            )
            self._log(
                f"capture failed scenario={plan.scenario} reason={exc}; fallback to placeholder"
            )
            fallback = self._execute_placeholder(plan, output_dir, reason=reason)
            fallback.warnings.extend(warnings)
            return fallback

        return CaptureResult(
            created_paths=created, backend_used="playwright", warnings=warnings
        )

    def _ensure_playwright_runtime(self) -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except Exception:
            self._log("playwright not installed; attempting pip install playwright")
            try:
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "playwright"],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except Exception:
                return False
            try:
                import playwright  # noqa: F401
                self._log("playwright package installation succeeded")
                return True
            except Exception:
                self._log("playwright package installation failed")
                return False

    def _launch_playwright_browser(self, playwright):
        try:
            return playwright.chromium.launch()
        except Exception as exc:
            if not self._is_missing_browser_error(exc):
                raise
            self._log("playwright browser missing; installing chromium runtime")
            if not self._install_playwright_browser():
                raise
            self._log("playwright chromium installation succeeded; retrying launch")
            return playwright.chromium.launch()

    def _is_missing_browser_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return (
            "executable doesn't exist" in message
            or "please run the following command to download new browsers" in message
            or "playwright install" in message
        )

    def _install_playwright_browser(self) -> bool:
        try:
            subprocess.run(
                [sys.executable, "-m", "playwright", "install", "chromium"],
                check=False,
                capture_output=True,
                text=True,
            )
            return True
        except Exception:
            self._log("playwright chromium installation failed")
            return False

    def _ensure_django_superuser(self) -> bool:
        try:
            from django.conf import settings
            from django.contrib.auth import get_user_model

            if not settings.configured:
                self._log("temp user ensure skipped: django settings not configured")
                return False

            user_model = get_user_model()
            username = self.capture_username or "showcaseuser"
            password = self.capture_password or "showcaseuser"
            user_obj = user_model.objects.filter(username=username).first()
            if user_obj is None:
                create_kwargs = {
                    user_model.USERNAME_FIELD: username,
                    "password": password,
                }
                email_field = getattr(user_model, "EMAIL_FIELD", None)
                if email_field:
                    create_kwargs[email_field] = f"{username}@example.com"
                user_model.objects.create_superuser(**create_kwargs)
                self._log(f"temp user created username={username}")
                self._temp_user_created = True
            else:
                user_obj.set_password(password)
                user_obj.is_active = True
                user_obj.is_staff = True
                user_obj.is_superuser = True
                user_obj.save(
                    update_fields=[
                        "password",
                        "is_active",
                        "is_staff",
                        "is_superuser",
                    ]
                )
                self._log(f"temp user updated username={username}")
            return True
        except Exception as exc:
            self._log(f"temp user ensure failed username={self.capture_username}: {exc}")
            return False

    def cleanup_temp_user(self) -> None:
        if not self.cleanup_temp_user_enabled:
            return
        try:
            from django.contrib.auth import get_user_model

            username = self.capture_username or "showcaseuser"
            user_model = get_user_model()
            user_obj = user_model.objects.filter(username=username).first()
            if user_obj is not None and (
                self._temp_user_created or username.startswith("showcase")
            ):
                user_obj.delete()
                self._log(f"temp user deleted username={username}")
            elif user_obj is not None:
                self._log(
                    f"temp user preserved username={username} reason=not-created-by-showcase"
                )
        except Exception as exc:
            self._log(f"temp user cleanup failed username={self.capture_username}: {exc}")
            return

    def _login_if_needed(self, page) -> bool:
        username_selectors = [
            "input[name='username']",
            "input#id_username",
            "input[autocomplete='username']",
        ]
        password_selectors = [
            "input[name='password']",
            "input#id_password",
            "input[autocomplete='current-password']",
        ]
        submit_selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "button:has-text('Log in')",
            "button:has-text('Sign in')",
        ]

        username_field = next(
            (
                selector
                for selector in username_selectors
                if page.locator(selector).count() > 0
            ),
            None,
        )
        password_field = next(
            (
                selector
                for selector in password_selectors
                if page.locator(selector).count() > 0
            ),
            None,
        )
        if username_field is None or password_field is None:
            self._log("login form not detected on page")
            return False

        page.locator(username_field).fill(self.capture_username)
        page.locator(password_field).fill(self.capture_password)

        submit_button = next(
            (
                selector
                for selector in submit_selectors
                if page.locator(selector).count() > 0
            ),
            None,
        )
        if submit_button is None:
            self._log("login form detected but submit button not found")
            return False
        page.locator(submit_button).click()
        page.wait_for_load_state("networkidle")
        return True

    def _diagnose_login_result(self, page) -> str | None:
        try:
            error_selectors = [
                ".errornote",
                ".alert-danger",
                ".errorlist",
                "[role='alert']",
            ]
            for selector in error_selectors:
                locator = page.locator(selector)
                if locator.count() > 0:
                    message = (locator.first.text_content() or "").strip()
                    if message:
                        return f"failed ({message})"
                    return f"failed (error element: {selector})"
        except Exception:
            return None

        try:
            username_visible = page.locator("input[name='username']").count() > 0
            password_visible = page.locator("input[name='password']").count() > 0
            if username_visible and password_visible:
                return "failed (still on login form after submit)"
        except Exception:
            return None

        return "success"

    def _resolve_url(self, plan: CapturePlan) -> str:
        base = (self.base_url or "").rstrip("/")
        route_path = plan.route_path or plan.route
        if route_path.startswith("http://") or route_path.startswith("https://"):
            return route_path
        if not route_path.startswith("/"):
            route_path = "/" + route_path
        return base + route_path
