from __future__ import annotations

import json
from pathlib import Path
from dataclasses import replace

from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand

from django_showcase.agent import load_agent_provider
from django_showcase.agent.base import SeedPlanningRequest
from django_showcase.agent.cache import SeedPlanCache
from django_showcase.agent.guardrails import SeedPlanGuardrails
from django_showcase.agent.operations import (
    AgentWarningCollector,
    safe_plan_frontend_routes,
    safe_plan_seed,
)
from django_showcase.agent.tools import build_schema_summary
from django_showcase.capture.capture import CaptureEngine
from django_showcase.capture.compiler import CapturePlanCompiler
from django_showcase.capture.plan import CapturePlan
from django_showcase.config import ShowcaseConfig, _load_prompt_file
from django_showcase.discovery.frontend import collect_route_snippets, detect_frontends
from django_showcase.discovery.models import inspect_models
from django_showcase.discovery.project import build_project_context
from django_showcase.discovery.urls import RouteInfo, discover_routes
from django_showcase.discovery.views import inspect_views
from django_showcase.report.builder import ReportBuilder
from django_showcase.report.manifest import write_manifest
from django_showcase.runtime.archive import build_showcase_zip
from django_showcase.runtime.database import scenario_runtime, scenario_transaction
from django_showcase.scenario.planner import PlannerInputs, ScenarioPlanner
from django_showcase.seed.executor import SeedExecutor
from django_showcase.seed.providers.agentic import AgenticProvider
from django_showcase.seed.validator import SeedPlanValidator


class Command(BaseCommand):
    help = "Generate scenario-first product documentation for a Django project."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--plan", action="store_true", help="Plan only without executing captures."
        )
        parser.add_argument(
            "--agentic",
            action="store_true",
            help="Enable agentic providers when configured.",
        )
        parser.add_argument(
            "--scenarios", action="store_true", help="Run in isolated scenario mode."
        )
        parser.add_argument(
            "--seed-strategy",
            choices=["goal_only", "all_pages"],
            default=None,
            help="Agentic seed policy when --agentic is enabled.",
        )
        parser.add_argument(
            "--frontend-dir",
            action="append",
            default=[],
            help="Additional frontend root to scan (can be provided multiple times).",
        )
        parser.add_argument(
            "--frontend",
            action="store_true",
            help="Run frontend routes only.",
        )
        parser.add_argument(
            "--backend",
            action="store_true",
            help="Run backend routes only.",
        )
        parser.add_argument(
            "--prompt-file",
            default=None,
            help="JSON file with prompt overrides for agentic mode.",
        )
        parser.add_argument(
            "--only", nargs="*", default=[], help="Limit execution to specific modules."
        )
        parser.add_argument(
            "--skip",
            nargs="*",
            default=[],
            help="Skip specific modules or route path segments (for example: admin).",
        )
        parser.add_argument(
            "--log",
            action="store_true",
            help="Enable concise capture logs (user create/login/delete/fallback reasons).",
        )

    def handle(self, *args, **options) -> None:
        verbose_capture_logs = bool(options.get("log")) or int(
            options.get("verbosity", 1)
        ) >= 2

        def capture_log(message: str) -> None:
            if verbose_capture_logs:
                self.stdout.write(f"[capture] {message}")

        config = ShowcaseConfig.from_settings()
        warnings = AgentWarningCollector()

        prompt_overrides = dict(config.prompt_overrides or {})
        if options["prompt_file"]:
            prompt_overrides.update(_load_prompt_file(Path(options["prompt_file"])))

        agentic: AgenticProvider | None = None
        if options["agentic"]:
            try:
                agentic = AgenticProvider(
                    agent=load_agent_provider(
                        config.agent_provider,
                        model=config.agent_model,
                        timeout_seconds=config.agent_timeout_seconds,
                        max_retries=config.agent_max_retries,
                        prompt_overrides=prompt_overrides,
                    ),
                    guardrails=SeedPlanGuardrails(max_objects=config.max_seed_objects),
                    cache=SeedPlanCache(config.output_dir / "cache"),
                )
            except ImproperlyConfigured as exc:
                warnings.warn(f"Agentic mode disabled: {exc}")

        frontend_roots = [
            config.frontend_dir,
            *config.frontend_dirs,
            *(Path(item) for item in options["frontend_dir"]),
        ]
        unique_roots: list[Path] = []
        seen_roots: set[str] = set()
        for root in frontend_roots:
            key = str(root.resolve()) if root.exists() else str(root)
            if key in seen_roots:
                continue
            seen_roots.add(key)
            unique_roots.append(root)

        frontend = detect_frontends(unique_roots)
        if agentic and frontend.framework != "django-mvt" and not frontend.routes:
            snippet_root = next(
                (root for root in unique_roots if root.exists()), config.frontend_dir
            )
            frontend.routes = safe_plan_frontend_routes(
                agentic,
                frontend.framework,
                collect_route_snippets(snippet_root),
                warnings,
            )
        frontend_summary = (
            f"Frontend: {frontend.framework} "
            f"({len(frontend.routes)} SPA routes, "
            f"{len(frontend.router_files)} router files, "
            f"{len(frontend.components)} components)"
        )
        self.stdout.write(frontend_summary)

        include_frontend, include_backend = _selected_route_sources(options)
        split_route_source_dirs = include_frontend and include_backend

        routes = discover_routes()
        routes += [
            RouteInfo(
                name=route.path.strip("/").replace("/", "_") or "home",
                pattern=route.path,
                module_id=route.module,
                view_name="SPA",
                is_get_supported=True,
                route_source="frontend",
                allowed_methods=("get",),
            )
            for route in frontend.routes
        ]
        routes = [
            route
            for route in routes
            if (route.route_source == "frontend" and include_frontend)
            or (route.route_source == "backend" and include_backend)
        ]
        views = inspect_views(routes)
        models = inspect_models()
        graph = ScenarioPlanner().build_graph(
            PlannerInputs(
                routes=routes,
                views=views,
                models=models,
                max_scenarios_per_module=config.max_scenarios_per_module,
                max_choices_per_field=config.max_choices_per_field,
            )
        )

        only_modules = set(_normalize_option_values(options.get("only", [])))
        skip_filters = {
            item.lower() for item in _normalize_option_values(options.get("skip", []))
        }

        if only_modules:
            graph.scenarios = {
                scenario_id: scenario
                for scenario_id, scenario in graph.scenarios.items()
                if scenario.module in only_modules
            }
            graph.modules = {
                module_id: module
                for module_id, module in graph.modules.items()
                if module_id in only_modules
            }

        if skip_filters:
            graph.scenarios = {
                scenario_id: scenario
                for scenario_id, scenario in graph.scenarios.items()
                if not _is_skipped_scenario(scenario.module, scenario.params, skip_filters)
            }
            graph.modules = {
                module_id: module
                for module_id, module in graph.modules.items()
                if module_id not in skip_filters
            }

        plans = CapturePlanCompiler().compile(graph)
        if split_route_source_dirs:
            plans = [
                replace(
                    plan,
                    captures=[
                        replace(
                            target,
                            output_path=f"{plan.route_source}/{target.output_path}",
                        )
                        for target in plan.captures
                    ],
                )
                for plan in plans
            ]
        write_manifest(
            config.output_dir / "manifest.json",
            plans,
            context=build_project_context(),
            frontend=frontend,
            scenarios=graph.scenarios,
            module_candidate_counts=graph.module_candidate_counts,
            warnings=warnings.messages,
        )

        self.stdout.write(self.style.SUCCESS("Planning Showcase"))
        for plan in plans:
            self.stdout.write(
                f"  - {plan.scenario} [{plan.route}] {len(plan.captures)} captures"
            )

        self.stdout.write(
            f"Estimated: {len(plans)} scenarios, "
            f"{sum(len(plan.captures) for plan in plans)} captures"
        )
        for module_id, candidate_count in sorted(graph.module_candidate_counts.items()):
            selected_count = sum(
                1
                for scenario in graph.scenarios.values()
                if scenario.module == module_id
            )
            self.stdout.write(
                "  - "
                f"{module_id}: selected {selected_count} of {candidate_count} "
                "candidates"
            )

        if options["plan"]:
            manifest_path = config.output_dir / "manifest.json"
            self.stdout.write(self.style.SUCCESS(f"Wrote plan to {manifest_path}"))
            return

        validator = SeedPlanValidator(max_objects=config.max_seed_objects)
        capture_engine = CaptureEngine(
            backend=config.capture_backend,
            base_url=config.capture_base_url,
            frontend_base_url=config.frontend_base_url,
            timeout_seconds=config.capture_timeout_seconds,
            capture_username=config.capture_admin_username,
            capture_password=config.capture_admin_password,
            cleanup_temp_user=config.capture_cleanup_temp_user,
            skipped_dir=config.output_dir / "skipped",
            split_sources=split_route_source_dirs,
            event_logger=capture_log,
        )
        scenario_mode = options["scenarios"] or config.scenario_mode

        created: list[str] = []
        seeded = 0
        capture_backends: set[str] = set()
        successful_plans: list[CapturePlan] = []
        seed_strategy = options["seed_strategy"] or config.agentic_seed_strategy
        try:
            with scenario_runtime(enabled=scenario_mode) as session:
                executor = SeedExecutor(session)
                schema_summary = build_schema_summary() if agentic else {}
                for plan in plans:
                    scenario = graph.scenarios[plan.scenario]
                    with scenario_transaction(session):
                        if agentic and (seed_strategy == "all_pages" or scenario.goal):
                            goal = scenario.goal or (
                                "Show a realistic demo state for route "
                                f"{scenario.route}."
                            )
                            seed_plan = safe_plan_seed(
                                agentic,
                                SeedPlanningRequest(
                                    scenario_id=scenario.id,
                                    goal=goal,
                                    schema_summary=schema_summary,
                                ),
                                fallback=scenario.seed.compile() if scenario.seed else None,
                                warnings=warnings,
                            )
                            if seed_plan is not None:
                                seeded += executor.execute(seed_plan).objects_created
                        elif scenario.seed:
                            seed_plan = validator.validate(scenario.seed.compile())
                            seeded += executor.execute(seed_plan).objects_created
                        capture_result = capture_engine.execute(
                            plan, config.screenshots_dir
                        )
                        capture_backends.add(capture_result.backend_used)
                        warnings.messages.extend(capture_result.warnings)
                        if capture_result.skipped:
                            skip_reason = capture_result.skipped_reason or "non-renderable route"
                            warnings.warn(
                                f"Skipped scenario {plan.scenario} ({plan.route}): {skip_reason}"
                            )
                            continue
                        successful_plans.append(plan)
                        created.extend(capture_result.created_paths)
        finally:
            capture_engine.cleanup_temp_user()

        manifest = write_manifest(
            config.output_dir / "manifest.json",
            successful_plans,
            context=build_project_context(),
            frontend=frontend,
            scenarios=graph.scenarios,
            module_candidate_counts=graph.module_candidate_counts,
            warnings=warnings.messages,
        )
        manifest["capture"]["backend"] = (
            "+".join(sorted(capture_backends)) if capture_backends else "none"
        )
        (config.output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        report_path = ReportBuilder().build(
            config.report_dir, successful_plans, manifest=manifest
        )
        archive_path = build_showcase_zip(
            config.output_dir, filename=config.archive_filename
        )
        for message in warnings.messages:
            self.stdout.write(self.style.WARNING(message))
        self.stdout.write(
            self.style.SUCCESS(f"Manifest scenarios: {len(manifest['scenarios'])}")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {seeded} ephemeral demo objects (rolled back)")
        )
        self.stdout.write(
            self.style.SUCCESS(f"Created {len(created)} capture artifacts")
        )
        self.stdout.write(self.style.SUCCESS(f"Report written to {report_path}"))
        self.stdout.write(self.style.SUCCESS(f"Archive written to {archive_path}"))


def _normalize_option_values(values: object) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        return [values]

    normalized: list[str] = []
    for item in values:
        if isinstance(item, str):
            normalized.append(item)
            continue
        normalized.extend(_normalize_option_values(item))
    return normalized


def _is_skipped_scenario(
    module_id: str, params: dict[str, object], skip_filters: set[str]
) -> bool:
    if module_id.lower() in skip_filters:
        return True

    route_path = str(params.get("route_path", "")).lower()
    if not route_path:
        return False

    segments = [segment for segment in route_path.split("/") if segment]
    return any(segment in skip_filters for segment in segments)


def _selected_route_sources(options: dict[str, object]) -> tuple[bool, bool]:
    frontend_only = bool(options.get("frontend"))
    backend_only = bool(options.get("backend"))

    if frontend_only and not backend_only:
        return True, False
    if backend_only and not frontend_only:
        return False, True
    return True, True
