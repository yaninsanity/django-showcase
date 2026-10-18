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
