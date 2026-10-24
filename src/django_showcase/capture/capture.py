from __future__ import annotations

import base64
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from time import sleep
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
    skipped: bool = False
    skipped_reason: str | None = None
    login_failed: bool = False
    login_failed_reason: str | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    failure_reason: str | None = None
    retryable: bool = False


class CaptureError(RuntimeError):
    """Raised when real browser capture is requested but cannot run safely."""


class CaptureEngine:
    def __init__(
        self,
        backend: Literal["auto", "playwright", "placeholder"] = "auto",
        base_url: str | None = None,
        frontend_base_url: str | None = None,
        timeout_seconds: float = 20.0,
        capture_username: str = "showcaseuser",
        capture_password: str = "showcaseuser",
        use_temp_user: bool = True,
        login_retry_attempts: int = 2,
        login_retry_delay_seconds: float = 0.5,
        skipped_dir: Path | None = None,
        split_sources: bool = False,
        event_logger: Callable[[str], None] | None = None,
    ) -> None:
        self.backend = backend
        self.base_url = base_url
        self.frontend_base_url = frontend_base_url
        self.timeout_seconds = timeout_seconds
        self.capture_username = capture_username
        self.capture_password = capture_password
        self.use_temp_user = use_temp_user
        self.login_retry_attempts = max(1, int(login_retry_attempts))
        self.login_retry_delay_seconds = max(0.0, float(login_retry_delay_seconds))
        self.skipped_dir = skipped_dir
        self.split_sources = split_sources
        self._temp_user_created = False
        self._auth_prepared = False
        self._state_lock = Lock()
        self._event_logger = event_logger

    def _log(self, message: str) -> None:
        if self._event_logger is not None:
            self._event_logger(message)

    def execute(self, plan: CapturePlan, output_dir: Path) -> CaptureResult:
        heuristic_reason = self._heuristic_skip_reason(plan)
        if heuristic_reason is not None:
            self._record_skip(plan, output_dir, heuristic_reason)
            return CaptureResult(
                backend_used="skipped",
                skipped=True,
                skipped_reason=heuristic_reason,
                failure_reason=heuristic_reason,
                retryable=False,
            )

        if self.backend == "placeholder":
            return self._execute_placeholder(
                plan,
                output_dir,
                reason="backend=placeholder",
            )
        if self.backend == "playwright":
            return self._execute_playwright(plan, output_dir)

        if self._select_base_url(plan):
            return self._execute_playwright(plan, output_dir)
        return self._execute_placeholder(
            plan,
            output_dir,
            reason="capture base URL is not set; placeholder is active",
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
        if not self._select_base_url(plan):
            return CaptureResult(
                backend_used="placeholder",
                warnings=[
                    f"capture base URL is not set for route_source={plan.route_source}; using placeholder captures."
                ],
                fallback_used=True,
                fallback_reason="capture base URL is not set",
                failure_reason="capture base URL is not set",
                retryable=False,
            )
        if not self._ensure_playwright_runtime():
            return CaptureResult(
                backend_used="placeholder",
                warnings=[
                    "Playwright runtime installation failed; using placeholder captures."
                ],
                fallback_used=True,
                fallback_reason="playwright runtime installation failed",
                failure_reason="playwright runtime installation failed",
                retryable=False,
            )
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return CaptureResult(
                backend_used="placeholder",
                warnings=[
                    f"Playwright unavailable; using placeholder captures ({exc})."
                ],
                fallback_used=True,
                fallback_reason=f"playwright unavailable: {exc}",
                failure_reason=f"playwright unavailable: {exc}",
                retryable=False,
            )

        created: list[str] = []
        warnings: list[str] = []
        login_failed = False
        login_failed_reason: str | None = None
        target_url = self._resolve_url(plan)
        user_ready = self._prepare_auth_user()
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
                probe_status = self._probe_page_status(page, target_url)
                if probe_status is not None:
                    reason = self._http_skip_reason(probe_status)
                    if reason is not None:
                        self._record_skip(plan, output_dir, reason)
                        context.close()
                        browser.close()
                        return CaptureResult(
                            backend_used="playwright",
                            warnings=warnings,
                            skipped=True,
                            skipped_reason=reason,
                            failure_reason=reason,
                            retryable=self._is_retryable_failure(reason),
                        )

                if not self._is_renderable_page(page):
                    reason = "non-renderable route"
                    self._record_skip(plan, output_dir, reason)
                    context.close()
                    browser.close()
                    return CaptureResult(
                        backend_used="playwright",
                        warnings=warnings,
                        skipped=True,
                        skipped_reason=reason,
                        failure_reason=reason,
                        retryable=self._is_retryable_failure(reason),
                    )

                for target in plan.captures:
                    page.set_viewport_size(
                        {"width": target.width, "height": target.height}
                    )
                    page.goto(target_url, wait_until="networkidle")
                    if self._should_skip_auto_login(target_url, plan):
                        self._log(
                            f"skip auto login for auth page scenario={plan.scenario} url={target_url}"
                        )
                    else:
                        if plan.route_source == "frontend":
                            self._log(
                                f"frontend auth probe scenario={plan.scenario} url={target_url}"
                            )
                        attempted, success, attempts, status = self._login_with_retry(
                            page,
                            route_source=plan.route_source,
                            target_url=target_url,
                            scenario_id=plan.scenario,
                            max_attempts=self.login_retry_attempts,
                            retry_delay_seconds=self.login_retry_delay_seconds,
                        )
                        if attempted and not success:
                            login_failed = True
                            login_failed_reason = status
                            warnings.append(
                                "Login failed for "
                                f"scenario={plan.scenario} after {attempts} attempts ({status})."
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
            fallback.login_failed = login_failed
            fallback.login_failed_reason = login_failed_reason
            fallback.fallback_used = True
            fallback.fallback_reason = str(exc)
            fallback.failure_reason = str(exc)
            fallback.retryable = self._is_retryable_failure(str(exc))
            return fallback

        return CaptureResult(
            created_paths=created,
            backend_used="playwright",
            warnings=warnings,
            login_failed=login_failed,
            login_failed_reason=login_failed_reason,
            retryable=False,
        )

    def _is_retryable_failure(self, reason: str) -> bool:
        lower = (reason or "").lower()
        non_retryable_markers = (
            "api endpoint",
            "post-only",
            "mutation route",
            "capture base url is not set",
            "playwright unavailable",
            "playwright runtime installation failed",
            "405 method not allowed",
            "403 forbidden",
        )
        if any(marker in lower for marker in non_retryable_markers):
            return False
        retryable_markers = (
            "timeout",
            "non-renderable route",
            "http 5",
            "500",
            "network",
            "connection",
            "failed",
            "error",
        )
        return any(marker in lower for marker in retryable_markers)

    def _login_with_retry(
        self,
        page,
        route_source: str,
        target_url: str,
        scenario_id: str,
        max_attempts: int = 2,
        retry_delay_seconds: float = 0.5,
    ) -> tuple[bool, bool, int, str]:
        attempted = False
        last_status = "not-attempted"
        attempts = 0
        for attempt in range(1, max_attempts + 1):
            submitted = self._login_if_needed(page, route_source)
            if not submitted:
                self._log(
                    f"{route_source} login not required for scenario={scenario_id}"
                )
                return False, True, 0, "not-required"

            attempted = True
            attempts = attempt
            last_status = self._diagnose_login_result(page) or "unknown"
            self._log(
                f"{route_source} login attempt={attempt}/{max_attempts} "
                f"scenario={scenario_id} status={last_status}"
            )
            if last_status == "success":
                return True, True, attempts, last_status

            if attempt < max_attempts:
                sleep(retry_delay_seconds)
                page.goto(target_url, wait_until="networkidle")

        self._log(
            f"{route_source} login failed after retries scenario={scenario_id} status={last_status}"
        )
        return attempted, False, attempts, last_status

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

    def _validate_existing_user(self) -> bool:
        try:
            from django.conf import settings
            from django.contrib.auth import get_user_model

            if not settings.configured:
                self._log("existing user validation skipped: django settings not configured")
                return False

            username = self.capture_username or ""
            if not username:
                self._log("existing user validation failed: username is empty")
                return False

            user_model = get_user_model()
            username_field = user_model.USERNAME_FIELD
            user_obj = user_model.objects.filter(**{username_field: username}).first()
            if user_obj is None:
                self._log(f"existing user validation failed: user {username} not found")
                return False
            if not getattr(user_obj, "is_active", True):
                self._log(f"existing user validation failed: user {username} is inactive")
                return False
            self._log(f"existing user validated username={username}")
            return True
        except Exception as exc:
            self._log(f"existing user validation failed username={self.capture_username}: {exc}")
            return False

    def _prepare_auth_user(self) -> bool:
        with self._state_lock:
            if self._auth_prepared:
                return True

            if not self.use_temp_user:
                ready = self._validate_existing_user()
                if ready:
                    self._auth_prepared = True
                return ready

            ready = self._ensure_django_superuser()
            if ready:
                self._auth_prepared = True
            return ready

    def prepare_auth_user(self) -> bool:
        return self._prepare_auth_user()

    def cleanup_temp_user(self) -> None:
        if not self.use_temp_user:
            self._log(
                f"temp user cleanup skipped username={self.capture_username} reason=existing-user-mode"
            )
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

    def _login_if_needed(self, page, route_source: str = "backend") -> bool:
        username_selectors = [
            "input[name='username']",
            "input#id_username",
            "input[autocomplete='username']",
            "input[name*='user' i]",
            "input[id*='user' i]",
            "input[placeholder*='username' i]",
            "input[placeholder*='user' i]",
            "input[placeholder*='email' i]",
            "input[type='email']",
            "input[type='text']",
            "input:not([type])",
        ]
        password_selectors = [
            "input[name='password']",
            "input#id_password",
            "input[autocomplete='current-password']",
            "input[name*='pass' i]",
            "input[id*='pass' i]",
            "input[placeholder*='password' i]",
            "input[type='password']",
        ]
        submit_selectors = [
            "input[type='submit']",
            "button[type='submit']",
            "button:has-text('Log in')",
            "button:has-text('Sign in')",
            "button:has-text('Login')",
            "button:has-text('Submit')",
            "button:has-text('Cook')",
        ]

        self._log_login_diagnostics(page, route_source)

        username_field = self._first_matching_selector(page, username_selectors)
        password_field = self._first_matching_selector(page, password_selectors)
        if username_field is None or password_field is None:
            self._log(
                f"{route_source} login form not detected on page "
                f"(username={username_field}, password={password_field})"
            )
            return False

        page.locator(username_field).first.fill(self.capture_username)
        page.locator(password_field).first.fill(self.capture_password)

        submit_button = self._first_matching_selector(page, submit_selectors)
        if submit_button is None:
            self._log(
                f"{route_source} login submit button not found; trying Enter key submit"
            )
            page.locator(password_field).first.press("Enter")
            page.wait_for_load_state("networkidle")
            return True

        page.locator(submit_button).first.click()
        page.wait_for_load_state("networkidle")
        return True

    def _first_matching_selector(self, page, selectors: list[str]) -> str | None:
        for selector in selectors:
            try:
                if page.locator(selector).count() > 0:
                    return selector
            except Exception:
                continue
        return None

    def _log_login_diagnostics(self, page, route_source: str) -> None:
        try:
            inputs = page.evaluate(
                """() => {
                    return Array.from(document.querySelectorAll('input')).slice(0, 12).map((el) => ({
                        type: el.getAttribute('type') || 'text',
                        name: el.getAttribute('name') || '',
                        id: el.getAttribute('id') || '',
                        placeholder: el.getAttribute('placeholder') || '',
                        autocomplete: el.getAttribute('autocomplete') || ''
                    }));
                }"""
            )
            self._log(f"{route_source} login probe inputs={inputs}")
        except Exception as exc:
            self._log(f"{route_source} login probe failed: {exc}")

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
        base = self._select_base_url(plan).rstrip("/")
        route_path = plan.route_path or plan.route
        if route_path.startswith("http://") or route_path.startswith("https://"):
            return route_path
        if not route_path.startswith("/"):
            route_path = "/" + route_path
        return base + route_path

    def _select_base_url(self, plan: CapturePlan) -> str:
        if plan.route_source == "frontend" and self.frontend_base_url:
            return self.frontend_base_url
        return self.base_url or ""

    def _heuristic_skip_reason(self, plan: CapturePlan) -> str | None:
        route_path = (plan.route_path or plan.route or "").lower()
        if not route_path:
            return "non-renderable route"

        non_renderable_prefixes = (
            "/api/",
            "/v1/",
            "/v2/",
            "/ajax/",
            "/graphql",
        )
        if any(route_path.startswith(prefix) for prefix in non_renderable_prefixes):
            return "api endpoint"

        if route_path.endswith((".json", ".xml", ".csv")):
            return "api endpoint"

        if re.search(r"\.(json|xml|csv)(/|$)", route_path):
            return "api endpoint"

        if self._is_delete_like_route(route_path):
            return "mutation route"

        if not plan.is_get_supported:
            return "post-only"

        if plan.allowed_methods:
            method_set = {method.lower() for method in plan.allowed_methods}
            if method_set.isdisjoint({"get", "head"}):
                return "post-only"

        return None

    def _is_delete_like_route(self, route_path: str) -> bool:
        return any(
            token in route_path
            for token in (
                "/delete/",
                "/remove/",
                "/destroy/",
                "/purge/",
            )
        )

    def _probe_page_status(self, page, target_url: str) -> int | None:
        try:
            response = page.goto(target_url, wait_until="domcontentloaded")
        except Exception as exc:
            self._log(f"probe navigation failed url={target_url}: {exc}")
            return None
        if response is None:
            return None
        status_getter = getattr(response, "status", None)
        if callable(status_getter):
            try:
                return int(status_getter())
            except Exception:
                return None
        try:
            return int(status_getter)
        except Exception:
            return None

    def _http_skip_reason(self, status_code: int) -> str | None:
        if status_code == 404:
            return "404 not found"
        if status_code == 405:
            return "405 method not allowed"
        if status_code == 403:
            return "403 forbidden"
        if status_code == 500:
            return "500 server error"
        if status_code in {200, 304}:
            return None
        if status_code >= 400:
            return f"http {status_code}"
        return None

    def _is_renderable_page(self, page) -> bool:
        try:
            content_type = (page.evaluate("() => document.contentType") or "").lower()
        except Exception:
            content_type = ""

        if content_type and "html" not in content_type:
            return False

        try:
            text = (page.locator("body").inner_text() or "").strip()
        except Exception:
            text = ""
        if not text:
            return False

        try:
            html = (page.content() or "").lower()
        except Exception:
            html = ""
        if "{\"detail\":" in html or "application/json" in html:
            return False

        return True

    def _record_skip(self, plan: CapturePlan, output_dir: Path, reason: str) -> None:
        self._log(
            f"skip capture scenario={plan.scenario} route={plan.route} reason={reason}"
        )
        reason_paths = self._build_skip_reason_paths(plan, output_dir)
        for reason_path in reason_paths:
            reason_path.parent.mkdir(parents=True, exist_ok=True)
            reason_path.write_text(
                "\n".join(
                    [
                        f"Scenario: {plan.scenario}",
                        f"Route: {plan.route}",
                        f"Route path: {plan.route_path or '-'}",
                        f"Resolved URL: {self._resolve_url(plan)}",
                        f"Reason: {reason}",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

    def cleanup_capture_artifacts(self, plan: CapturePlan, output_dir: Path) -> None:
        # Retries should replace stale fallback/skip artifacts from earlier attempts.
        for target in plan.captures:
            target_path = output_dir / target.output_path
            for path in (target_path, target_path.with_suffix(".txt")):
                try:
                    if path.exists():
                        path.unlink()
                except Exception:
                    continue
            self._prune_empty_parent_dirs(target_path.parent, output_dir)

        for reason_path in self._build_skip_reason_paths(plan, output_dir):
            try:
                if reason_path.exists():
                    reason_path.unlink()
            except Exception:
                continue
            base_dir = self.skipped_dir or output_dir
            self._prune_empty_parent_dirs(reason_path.parent, base_dir)

    def _build_skip_reason_paths(self, plan: CapturePlan, output_dir: Path) -> list[Path]:
        base_dir = self.skipped_dir or output_dir
        paths: list[Path] = []
        for target in plan.captures:
            output_path = Path(target.output_path)
            if self.split_sources and output_path.parts[:1] != (plan.route_source,):
                output_path = Path(plan.route_source) / output_path
            paths.append((base_dir / output_path).with_suffix(".txt"))
        return paths

    def _prune_empty_parent_dirs(self, start: Path, stop: Path) -> None:
        current = start
        stop_resolved = stop.resolve()
        while True:
            try:
                current_resolved = current.resolve()
            except Exception:
                break
            if current_resolved == stop_resolved:
                break
            if not current.exists() or not current.is_dir():
                current = current.parent
                continue
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent

    def _should_skip_auto_login(self, target_url: str, plan: CapturePlan) -> bool:
        path = (plan.route_path or "").lower()
        url = target_url.lower()
        auth_tokens = (
            "/login",
            "/signin",
            "/sign-in",
            "/register",
            "/signup",
            "/sign-up",
            "/auth/login",
            "/auth/register",
        )
        return any(token in path or token in url for token in auth_tokens)
