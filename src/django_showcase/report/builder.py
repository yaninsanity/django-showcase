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
