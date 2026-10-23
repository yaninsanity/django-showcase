from pathlib import Path

from django_showcase.capture.capture import CaptureEngine
from django_showcase.capture.plan import CapturePlan, CaptureTarget


def _plan() -> CapturePlan:
    return CapturePlan(
        module="orders",
        scenario="orders.pending",
        route="orders",
        route_path="/orders/",
        actor="staff",
        seed_provider="deterministic",
        estimated_objects=3,
        captures=[
            CaptureTarget(
                viewport="desktop",
                width=800,
                height=600,
                output_path="orders/pending/desktop.png",
            )
        ],
    )


def test_placeholder_capture_creates_png_and_metadata(tmp_path: Path):
    result = CaptureEngine(backend="placeholder").execute(_plan(), tmp_path)

    output = tmp_path / "orders/pending/desktop.png"
    meta = tmp_path / "orders/pending/desktop.txt"
    assert result.backend_used == "placeholder"
    assert not result.warnings
    assert str(output) in result.created_paths
    assert output.exists()
    assert meta.exists()


def test_auto_backend_without_base_url_uses_placeholder(tmp_path: Path):
    result = CaptureEngine(backend="auto", base_url=None).execute(_plan(), tmp_path)

    assert result.backend_used == "placeholder"
    assert (tmp_path / "orders/pending/desktop.png").exists()


def test_resolve_url_prefers_route_path():
    engine = CaptureEngine(backend="placeholder", base_url="http://localhost:8000")
    assert engine._resolve_url(_plan()) == "http://localhost:8000/orders/"


def test_login_if_needed_fills_admin_form_and_submits():
    engine = CaptureEngine(
        backend="auto",
        base_url="http://localhost:8000",
        capture_username="showcaseuser",
        capture_password="showcaseuser",
    )
    calls: list[tuple[str, str, str]] = []

    class FakeLocator:
        def __init__(self, selector: str):
            self.selector = selector
            self.first = self

        def count(self):
            return 1 if self.selector in {
                "input[name='username']",
                "input[name='password']",
                "input[type='submit']",
            } else 0

        def fill(self, value: str):
            calls.append(("fill", self.selector, value))

        def click(self):
            calls.append(("click", self.selector, ""))

        def press(self, key: str):
            calls.append(("press", self.selector, key))

    class FakePage:
        def locator(self, selector: str):
            return FakeLocator(selector)

        def evaluate(self, *_args, **_kwargs):
            return []

        def wait_for_load_state(self, *_args, **_kwargs):
            return None

    engine._ensure_django_superuser = lambda: None
    result = engine._login_if_needed(FakePage())

    assert result is True
    assert ("fill", "input[name='username']", "showcaseuser") in calls
    assert ("fill", "input[name='password']", "showcaseuser") in calls
    assert ("click", "input[type='submit']", "") in calls


def test_cleanup_temp_user_deletes_demo_user(monkeypatch):
    engine = CaptureEngine(
        backend="auto",
        base_url="http://localhost:8000",
        capture_username="showcaseuser",
        capture_password="showcaseuser",
        cleanup_temp_user=True,
    )

    class FakeUser:
        def __init__(self):
            self.deleted = False

        def delete(self):
            self.deleted = True

    fake_user = FakeUser()

    class FakeManager:
        @staticmethod
        def filter(**_kwargs):
            return type("Result", (), {"first": lambda *_args, **_kwargs: fake_user})()

    class FakeUserModel:
        objects = FakeManager()

    import sys
    import types

    fake_django = types.ModuleType("django")
    fake_contrib = types.ModuleType("django.contrib")
    fake_contrib.__path__ = []
    auth_module = types.ModuleType("django.contrib.auth")
    auth_module.get_user_model = lambda: FakeUserModel
    fake_django.contrib = fake_contrib
    fake_contrib.auth = auth_module

    monkeypatch.setitem(sys.modules, "django", fake_django)
    monkeypatch.setitem(sys.modules, "django.contrib", fake_contrib)
    monkeypatch.setitem(sys.modules, "django.contrib.auth", auth_module)

    engine.cleanup_temp_user()
    assert fake_user.deleted is True


def test_ensure_django_superuser_creates_user_with_password(monkeypatch):
    engine = CaptureEngine(
        backend="auto",
        base_url="http://localhost:8000",
        capture_username="showcaseuser",
        capture_password="showcasepass",
        cleanup_temp_user=True,
    )
    created: dict[str, str] = {}

    class FakeManager:
        @staticmethod
        def filter(**_kwargs):
            return type("Result", (), {"first": lambda *_args, **_kwargs: None})()

        @staticmethod
        def create_superuser(**kwargs):
            created.update(kwargs)
            return object()

    class FakeUserModel:
        USERNAME_FIELD = "username"
        EMAIL_FIELD = "email"
        objects = FakeManager()

    import sys
    import types

    conf_module = types.ModuleType("django.conf")
    conf_module.settings = types.SimpleNamespace(configured=True)
    auth_module = types.ModuleType("django.contrib.auth")
    auth_module.get_user_model = lambda: FakeUserModel

    monkeypatch.setitem(sys.modules, "django.conf", conf_module)
    monkeypatch.setitem(sys.modules, "django.contrib.auth", auth_module)

    engine._ensure_django_superuser()

    assert created["username"] == "showcaseuser"
    assert created["password"] == "showcasepass"
    assert created["email"] == "showcaseuser@example.com"


def test_playwright_reinstalls_missing_browser_and_retries(monkeypatch, tmp_path: Path):
    launch_count = {"value": 0}

    class FakePage:
        def __init__(self):
            self.url = "http://localhost:8000/orders/"

        def set_default_timeout(self, *_args, **_kwargs):
            pass

        def set_viewport_size(self, *_args, **_kwargs):
            pass

        def goto(self, url: str, **_kwargs):
            self.url = url
            return type("FakeResponse", (), {"status": lambda self: 200})()

        def locator(self, selector: str):
            if selector == "body":
                return type(
                    "BodyLocator",
                    (),
                    {
                        "count": lambda self: 1,
                        "inner_text": lambda self: "Orders dashboard",
                    },
                )()

            class FakeLocator:
                def __init__(self, selector: str):
                    self.selector = selector

                def count(self):
                    return 1 if self.selector == "input[name='username']" else 0

                def fill(self, value: str):
                    return value

                def click(self):
                    return None

            return FakeLocator(selector)

        def evaluate(self, *_args, **_kwargs):
            return "text/html"

        def content(self):
            return "<html><body>Orders dashboard</body></html>"

        def screenshot(self, path: str, **_kwargs):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_bytes(b"actual-png")

    class FakeBrowser:
        def new_page(self):
            return FakePage()

        def close(self):
            pass

        def new_context(self):
            class FakeContext:
                def new_page(self):
                    return FakePage()

                def close(self):
                    pass

            return FakeContext()

    class FakeChromium:
        def launch(self):
            launch_count["value"] += 1
            if launch_count["value"] == 1:
                raise RuntimeError(
                    "Executable doesn't exist. Please run playwright install"
                )
            return FakeBrowser()

    class FakePlaywrightSession:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_sync_playwright():
        return FakePlaywrightSession()

    def fake_run(*args, **kwargs):
        return type("Result", (), {"returncode": 0})()

    import sys
    import types

    fake_playwright_module = types.ModuleType("playwright")
    fake_sync_api_module = types.ModuleType("playwright.sync_api")
    fake_sync_api_module.sync_playwright = fake_sync_playwright
    fake_playwright_module.sync_api = fake_sync_api_module
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api_module)
    monkeypatch.setattr("subprocess.run", fake_run)

    result = CaptureEngine(
        backend="auto",
        base_url="http://localhost:8000",
        timeout_seconds=5.0,
    ).execute(_plan(), tmp_path)

    assert result.backend_used == "playwright"
    assert result.created_paths
    assert (tmp_path / "orders/pending/desktop.png").read_bytes() == b"actual-png"
    assert launch_count["value"] == 2


def test_safe_capture_heuristic_skips_api_endpoints(tmp_path: Path):
    plan = CapturePlan(
        module="api",
        scenario="api.list.default",
        route="api:list",
        route_path="/api/orders/",
        actor=None,
        seed_provider="existing",
        estimated_objects=0,
        captures=[
            CaptureTarget(
                viewport="desktop",
                width=800,
                height=600,
                output_path="api/list/desktop.png",
            )
        ],
    )
    result = CaptureEngine(backend="auto", base_url="http://localhost:8000").execute(
        plan, tmp_path
    )

    assert result.skipped is True
    assert result.skipped_reason == "api endpoint"
    assert not result.created_paths


def test_safe_capture_heuristic_skips_post_only_route(tmp_path: Path):
    plan = CapturePlan(
        module="orders",
        scenario="orders.submit.default",
        route="orders-submit",
        route_path="/orders/submit/",
        actor=None,
        seed_provider="existing",
        estimated_objects=0,
        is_get_supported=False,
        allowed_methods=("post",),
        captures=[
            CaptureTarget(
                viewport="desktop",
                width=800,
                height=600,
                output_path="orders/submit/desktop.png",
            )
        ],
    )
    result = CaptureEngine(backend="auto", base_url="http://localhost:8000").execute(
        plan, tmp_path
    )

    assert result.skipped is True
    assert result.skipped_reason == "post-only"


def test_safe_capture_skips_status_404(monkeypatch, tmp_path: Path):
    class FakeResponse:
        def status(self):
            return 404

    class FakeBodyLocator:
        def inner_text(self):
            return "Not Found"

        def count(self):
            return 0

    class FakePage:
        url = "http://localhost:8000/orders/"

        def set_default_timeout(self, *_args, **_kwargs):
            return None

        def set_viewport_size(self, *_args, **_kwargs):
            return None

        def goto(self, *_args, **_kwargs):
            return FakeResponse()

        def locator(self, selector: str):
            if selector == "body":
                return FakeBodyLocator()
            return FakeBodyLocator()

        def evaluate(self, *_args, **_kwargs):
            return "text/html"

        def content(self):
            return "<html><body>Not Found</body></html>"

        def screenshot(self, *_args, **_kwargs):
            raise AssertionError("screenshot should not be called for 404")

    class FakeContext:
        def new_page(self):
            return FakePage()

        def close(self):
            return None

    class FakeBrowser:
        def new_context(self):
            return FakeContext()

        def close(self):
            return None

    class FakePlaywrightSession:
        class chromium:
            @staticmethod
            def launch():
                return FakeBrowser()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_sync_playwright():
        return FakePlaywrightSession()

    import sys
    import types

    fake_playwright_module = types.ModuleType("playwright")
    fake_sync_api_module = types.ModuleType("playwright.sync_api")
    fake_sync_api_module.sync_playwright = fake_sync_playwright
    fake_playwright_module.sync_api = fake_sync_api_module
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_sync_api_module)

    result = CaptureEngine(
        backend="playwright",
        base_url="http://localhost:8000",
        skipped_dir=tmp_path / "skipped",
    ).execute(_plan(), tmp_path)

    assert result.skipped is True
    assert result.skipped_reason == "404 not found"
    reason_file = (
        tmp_path
        / "skipped"
        / "orders"
        / "orders__pending"
        / "skip_reason.txt"
    )
    assert reason_file.exists()
    assert "404 not found" in reason_file.read_text(encoding="utf-8")


def test_should_skip_auto_login_for_login_and_register_paths():
    engine = CaptureEngine(backend="auto", base_url="http://localhost:8000")

    login_plan = CapturePlan(
        module="auth",
        scenario="auth.login.default",
        route="login",
        route_path="/auth/login/",
        actor=None,
        seed_provider="existing",
        estimated_objects=0,
        captures=[],
        route_source="frontend",
    )
    register_plan = CapturePlan(
        module="auth",
        scenario="auth.register.default",
        route="register",
        route_path="/register/",
        actor=None,
        seed_provider="existing",
        estimated_objects=0,
        captures=[],
        route_source="backend",
    )
    orders_plan = CapturePlan(
        module="orders",
        scenario="orders.list.default",
        route="orders",
        route_path="/orders/",
        actor=None,
        seed_provider="existing",
        estimated_objects=0,
        captures=[],
    )

    assert engine._should_skip_auto_login("http://localhost:5173/auth/login/", login_plan) is True
    assert engine._should_skip_auto_login("http://localhost:5173/register/", register_plan) is True
    assert engine._should_skip_auto_login("http://localhost:5173/orders/", orders_plan) is False


def test_duplicate_url_is_skipped_on_second_plan(tmp_path: Path):
    engine = CaptureEngine(backend="placeholder", base_url="http://localhost:8000")
    first_plan = CapturePlan(
        module="orders",
        scenario="orders.default",
        route="orders",
        route_path="/orders/",
        actor=None,
        seed_provider="existing",
        estimated_objects=0,
        captures=[
            CaptureTarget(
                viewport="desktop",
                width=800,
                height=600,
                output_path="orders/default/desktop.png",
            )
        ],
    )
    second_plan = CapturePlan(
        module="orders",
        scenario="orders.high_volume",
        route="orders",
        route_path="/orders/",
        actor=None,
        seed_provider="deterministic",
        estimated_objects=25,
        captures=[
            CaptureTarget(
                viewport="desktop",
                width=800,
                height=600,
                output_path="orders/high_volume/desktop.png",
            )
        ],
    )

    first = engine.execute(first_plan, tmp_path)
    second = engine.execute(second_plan, tmp_path)

    assert first.skipped is False
    assert second.skipped is True
    assert second.skipped_reason == "duplicate url"
