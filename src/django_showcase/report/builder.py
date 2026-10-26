from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from django_showcase.capture.plan import CapturePlan

_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "report.html"

_CARD = """<article class="scenario-card">
  <h3>{title}</h3>
  <p><strong>Route:</strong> {route}</p>
  <p><strong>Actor:</strong> {actor}</p>
  <p><strong>Seed:</strong> {seed_provider} ({objects} objects)</p>
</article>"""

_SECTION = """<section class="module">
  <h2>{module}</h2>
    <p><strong>Coverage:</strong> {selected} of {candidates} planned candidates</p>
  <div class="scenario-grid">{cards}</div>
</section>"""

_SUMMARY = """<section class="module">
    <h2>Frontend Summary</h2>
    <p><strong>Framework:</strong> {framework}</p>
    <p><strong>Strategy Profile:</strong> {profile}</p>
    <p><strong>Capture Backend:</strong> {capture_backend}</p>
    <p><strong>Login Failed Pages:</strong> {login_failed_pages}</p>
    <div><strong>Login Failed Details:</strong>{login_failed_details}</div>
    <p><strong>Fallback Pages:</strong> {fallback_pages}</p>
    <div><strong>Fallback Details:</strong>{fallback_details}</div>
    <p><strong>Issue Skipped Pages:</strong> {issue_skipped_pages}</p>
    <div><strong>Issue Skipped Details:</strong>{issue_skipped_grouped_details}</div>
    <p><strong>SPA Routes:</strong> {routes}</p>
    <p><strong>Router Files:</strong> {router_files}</p>
    <p><strong>Discovered Components:</strong> {components}</p>
    <p><strong>Warnings:</strong> {warnings}</p>
</section>"""


class ReportBuilder:
    def build(
        self,
        report_dir: Path,
        plans: list[CapturePlan],
        manifest: dict[str, object] | None = None,
    ) -> Path:
        report_dir.mkdir(parents=True, exist_ok=True)
        grouped: dict[str, list[CapturePlan]] = defaultdict(list)
        for plan in plans:
            grouped[plan.module].append(plan)

        module_sections = []
        module_meta = {
            entry["module"]: entry for entry in (manifest or {}).get("modules", [])
        }
        for module, module_plans in sorted(grouped.items()):
            cards = [
                _CARD.format(
                    title=plan.scenario,
                    route=plan.route,
                    actor=plan.actor or "default",
                    seed_provider=plan.seed_provider,
                    objects=plan.estimated_objects,
                )
                for plan in sorted(module_plans, key=lambda item: item.scenario)
            ]
            meta = module_meta.get(
                module, {"selected": len(module_plans), "candidates": len(module_plans)}
            )
            module_sections.append(
                _SECTION.format(
                    module=module.title(),
                    selected=meta["selected"],
                    candidates=meta["candidates"],
                    cards="\n".join(cards),
                )
            )

        frontend = (manifest or {}).get("frontend") or {}
        summary = _SUMMARY.format(
            framework=frontend.get("framework", "django-mvt"),
            profile=frontend.get("profile", frontend.get("framework", "django-mvt")),
            capture_backend=((manifest or {}).get("capture") or {}).get(
                "backend", "unknown"
            ),
            login_failed_pages=((manifest or {}).get("capture") or {}).get(
                "login_failed_pages", 0
            ),
            login_failed_details=_format_capture_issue_details(
                ((manifest or {}).get("capture") or {}).get("login_failed_details", [])
            ),
            fallback_pages=((manifest or {}).get("capture") or {}).get(
                "fallback_pages", 0
            ),
            fallback_details=_format_capture_issue_details(
                ((manifest or {}).get("capture") or {}).get("fallback_details", [])
            ),
            issue_skipped_pages=((manifest or {}).get("capture") or {}).get(
                "issue_skipped_pages", 0
            ),
            issue_skipped_grouped_details=_format_issue_skip_grouped_details(
                ((manifest or {}).get("capture") or {}).get("issue_skipped_details", [])
            ),
            routes=frontend.get("routes", 0),
            router_files=len(frontend.get("router_files", [])),
            components=frontend.get("components", 0),
            warnings=len((manifest or {}).get("warnings", [])),
        )
        module_sections.insert(0, summary)

        html = _TEMPLATE_PATH.read_text(encoding="utf-8").replace(
            "__SECTIONS__", "\n".join(module_sections)
        )

        output_path = report_dir / "index.html"
        output_path.write_text(html, encoding="utf-8")
        return output_path

    def build_pdf(
        self,
        report_dir: Path,
        screenshot_paths: list[Path],
        filename: str = "screenshots.pdf",
    ) -> Path | None:
        images: list[Path] = [
            path
            for path in screenshot_paths
            if path.suffix.lower() in {".png", ".jpg", ".jpeg"} and path.exists()
        ]
        if not images:
            return None

        try:
            from PIL import Image
        except (
            Exception
        ) as exc:  # pragma: no cover - exercised by integration environments
            raise RuntimeError(
                "PDF export requires Pillow. Install it with `pip install Pillow`."
            ) from exc

        report_dir.mkdir(parents=True, exist_ok=True)
        output_path = report_dir / filename
        first: Image.Image | None = None
        rest: list[Image.Image] = []
        try:
            for index, path in enumerate(images):
                image = Image.open(path).convert("RGB")
                if index == 0:
                    first = image
                else:
                    rest.append(image)

            if first is None:
                return None

            first.save(output_path, "PDF", save_all=True, append_images=rest)
            return output_path
        finally:
            if first is not None:
                first.close()
            for image in rest:
                image.close()


def _format_capture_issue_details(items: list[object]) -> str:
    rows: list[str] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        scenario = str(entry.get("scenario", "unknown"))
        route = str(entry.get("route", "unknown"))
        reason = str(entry.get("reason", "unknown"))
        rows.append(f"<li>{scenario} ({route}): {reason}</li>")
    return f"<ul>{''.join(rows)}</ul>" if rows else "<p>none</p>"


def _format_issue_skip_grouped_details(items: list[object]) -> str:
    grouped: dict[str, list[str]] = defaultdict(list)
    for entry in items:
        if not isinstance(entry, dict):
            continue
        reason = str(entry.get("reason", "unknown"))
        scenario = str(entry.get("scenario", "unknown"))
        route = str(entry.get("route", "unknown"))
        grouped[reason].append(f"{scenario} ({route})")

    if not grouped:
        return "<p>none</p>"

    sections: list[str] = []
    for reason, routes in sorted(grouped.items()):
        route_items = "".join(f"<li>{route}</li>" for route in routes)
        sections.append(
            f"<p><strong>{reason}:</strong> {len(routes)}</p><ul>{route_items}</ul>"
        )
    return "".join(sections)
