from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from time import perf_counter

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
            help="Enable experimental agentic providers when configured.",
        )
        parser.add_argument(
            "--scenarios",
            action="store_true",
            help="Run experimental isolated scenario mode.",
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
            help=(
                "Enable concise capture logs "
                "(user create/login/delete/fallback reasons)."
            ),
        )
        parser.add_argument(
            "--mobile",
            action="store_true",
            help="Capture mobile viewport screenshots.",
        )
        parser.add_argument(
            "--desktop",
            action="store_true",
            help="Capture desktop viewport screenshots.",
        )
        parser.add_argument(
            "--pdf",
            action="store_true",
            help=(
                "Generate an additional PDF report that includes all "
                "captured screenshots."
            ),
        )
        parser.add_argument(
            "--timing",
            action="store_true",
            help="Print total command duration from start to finish.",
        )

    def handle(self, *args, **options) -> None:
        timing_enabled = bool(options.get("timing"))
        started_at = perf_counter()

        def emit_total_duration() -> None:
            if timing_enabled:
                elapsed = perf_counter() - started_at
                self.stdout.write(self.style.SUCCESS(f"Total duration: {elapsed:.2f}s"))

        verbose_capture_logs = (
            bool(options.get("log")) or int(options.get("verbosity", 1)) >= 2
        )

        def capture_log(message: str) -> None:
            if verbose_capture_logs:
                self.stdout.write(f"[capture] {message}")

        config = ShowcaseConfig.from_settings()
        warnings = AgentWarningCollector()

        if options["agentic"]:
            self.stdout.write(
                self.style.WARNING(
                    "EXPERIMENTAL: --agentic is not production-tested yet; "
                    "use only for preview runs and review output manually."
                )
            )

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

        include_mobile = bool(options.get("mobile"))
        include_desktop = bool(options.get("desktop"))
        if not include_mobile and not include_desktop:
            self.stdout.write(
                self.style.WARNING(
                    "No device selected. Use --mobile and/or --desktop to run captures."
                )
            )
            emit_total_duration()
            return
        split_device_dirs = include_mobile and include_desktop

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
                if not _is_skipped_scenario(
                    scenario.module, scenario.params, skip_filters
                )
            }
            graph.modules = {
                module_id: module
                for module_id, module in graph.modules.items()
                if module_id not in skip_filters
            }

        scenario_mode = options["scenarios"] or config.scenario_mode

        plans = CapturePlanCompiler().compile(
            graph,
            include_desktop=include_desktop,
            include_mobile=include_mobile,
            split_devices=split_device_dirs,
        )
        if not scenario_mode:
            planned_count = len(plans)
            plans = _collapse_plans_for_non_scenario_mode(plans)
            if len(plans) < planned_count:
                self.stdout.write(
                    self.style.WARNING(
                        "SCENARIO_MODE disabled: collapsing duplicate "
                        "scenario captures per URL."
                    )
                )
        if split_route_source_dirs:
            plans = [
                replace(
                    plan,
                    captures=[
                        replace(
                            target,
                            output_path=_with_route_source_prefix(
                                target.output_path,
                                plan.route_source,
                                split_device_dirs,
                            ),
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
            emit_total_duration()
            return

        validator = SeedPlanValidator(max_objects=config.max_seed_objects)
        capture_engine = CaptureEngine(
            backend=config.capture_backend,
            base_url=config.capture_base_url,
            frontend_base_url=config.frontend_base_url,
            timeout_seconds=config.capture_timeout_seconds,
            capture_username=config.capture_admin_username,
            capture_password=config.capture_admin_password,
            use_temp_user=config.capture_use_temp_user,
            skipped_dir=config.output_dir / "skipped",
            split_sources=split_route_source_dirs,
            event_logger=capture_log,
        )
        if config.capture_use_temp_user:
            self.stdout.write(
                "Capture auth mode: temporary superuser " "(auto create/delete)."
            )
            self.stdout.write(
                self.style.WARNING(
                    "Temp user mode needs database write access. "
                    "If your runtime cannot write to DB (for example containerized "
                    "HTTP-only access), set CAPTURE_USE_TEMP_USER=False and provide "
                    "CAPTURE_ADMIN_USERNAME/CAPTURE_ADMIN_PASSWORD for an existing user."
                )
            )
        else:
            self.stdout.write(
                "Capture auth mode: existing user " "(no auto create/delete)."
            )
        capture_workers = max(1, int(config.capture_workers))
        if scenario_mode and capture_workers > 1:
            warnings.warn(
                "SCENARIO_MODE uses transaction-scoped seeding; "
                "forcing CAPTURE_WORKERS=1."
            )
            capture_workers = 1
        if scenario_mode:
            self.stdout.write(
                self.style.WARNING(
                    "EXPERIMENTAL: SCENARIO_MODE seeding/capture flow is still "
                    "evolving; validate results before sharing."
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    "SCENARIO_MODE enabled: each scenario runs in an isolated "
                    "transaction and rolls back after capture."
                )
            )

        created: list[str] = []
        seeded = 0
        capture_backends: set[str] = set()
        successful_plans: list[CapturePlan] = []
        login_failed_pages = 0
        fallback_pages = 0
        login_failed_details: list[dict[str, str]] = []
        fallback_details: list[dict[str, str]] = []
        issue_skipped_pages = 0
        issue_skipped_details: list[dict[str, str]] = []
        issue_skipped_by_reason: dict[str, int] = {}
        seed_strategy = options["seed_strategy"] or config.agentic_seed_strategy
        try:
            with scenario_runtime(enabled=scenario_mode) as session:
                executor = SeedExecutor(session)
                schema_summary = build_schema_summary() if agentic else {}

                if not capture_engine.prepare_auth_user():
                    warnings.warn(
                        "Capture login user is not ready; "
                        "captures may fail on authenticated routes."
                    )

                def run_capture(plan: CapturePlan):
                    result = capture_engine.execute(plan, config.screenshots_dir)
                    return plan, result

                def collect_capture_result(
                    plan: CapturePlan,
                    capture_result,
                    allow_defer: bool = True,
                ) -> None:
                    nonlocal login_failed_pages, fallback_pages, issue_skipped_pages
                    capture_backends.add(capture_result.backend_used)
                    warnings.messages.extend(capture_result.warnings)
                    if allow_defer and getattr(capture_result, "retryable", False):
                        return
                    if capture_result.login_failed and not getattr(
                        capture_result, "retryable", False
                    ):
                        login_failed_pages += 1
                        login_failed_details.append(
                            {
                                "scenario": plan.scenario,
                                "route": plan.route,
                                "reason": capture_result.login_failed_reason
                                or "login failed",
                            }
                        )
                    if capture_result.fallback_used and not getattr(
                        capture_result, "retryable", False
                    ):
                        fallback_pages += 1
                        fallback_details.append(
                            {
                                "scenario": plan.scenario,
                                "route": plan.route,
                                "reason": capture_result.fallback_reason
                                or "fallback used",
                            }
                        )
                    if capture_result.skipped and not getattr(
                        capture_result, "retryable", False
                    ):
                        skip_reason = (
                            capture_result.skipped_reason or "non-renderable route"
                        )
                        if skip_reason not in {
                            "api endpoint",
                            "post-only",
                            "mutation route",
                        }:
                            issue_skipped_pages += 1
                            issue_skipped_details.append(
                                {
                                    "scenario": plan.scenario,
                                    "route": plan.route,
                                    "reason": skip_reason,
                                }
                            )
                            issue_skipped_by_reason[skip_reason] = (
                                issue_skipped_by_reason.get(skip_reason, 0) + 1
                            )
                        warnings.warn(
                            f"Skipped scenario {plan.scenario} "
                            f"({plan.route}): {skip_reason}"
                        )
                        return
                    successful_plans.append(plan)
                    created.extend(capture_result.created_paths)

                def execute_with_deferred_retries(
                    plan_list: list[CapturePlan],
                    workers: int,
                ) -> None:
                    retry_queue: list[CapturePlan] = []

                    def is_retryable(result) -> bool:
                        return bool(getattr(result, "retryable", False))

                    def retry_reason(result) -> str:
                        return str(
                            getattr(result, "failure_reason", None)
                            or getattr(result, "skipped_reason", None)
                            or "retryable failure"
                        )

                    if workers <= 1:
                        for plan in plan_list:
                            capture_result = capture_engine.execute(
                                plan, config.screenshots_dir
                            )
                            if is_retryable(capture_result):
                                retry_queue.append(plan)
                                capture_log(
                                    f"retry queued scenario={plan.scenario} "
                                    f"reason={retry_reason(capture_result)}"
                                )
                            collect_capture_result(plan, capture_result)
                    else:
                        with ThreadPoolExecutor(max_workers=workers) as pool:
                            futures = [
                                pool.submit(run_capture, plan) for plan in plan_list
                            ]
                            capture_log(
                                f"parallel capture submitted tasks={len(futures)} "
                                f"workers={workers}"
                            )
                            completed = 0
                            for future in as_completed(futures):
                                plan, capture_result = future.result()
                                completed += 1
                                capture_log(
                                    f"parallel capture progress completed="
                                    f"{completed}/{len(futures)} "
                                    f"scenario={plan.scenario}"
                                )
                                if is_retryable(capture_result):
                                    retry_queue.append(plan)
                                    capture_log(
                                        f"retry queued scenario={plan.scenario} "
                                        f"reason={retry_reason(capture_result)}"
                                    )
                                collect_capture_result(plan, capture_result)

                    if workers > 1 and retry_queue:
                        capture_log(
                            f"deferred retry start count={len(retry_queue)} "
                            f"mode=sequential"
                        )
                        for plan in retry_queue:
                            capture_log(
                                f"deferred retry attempt scenario={plan.scenario}"
                            )
                            capture_engine.cleanup_capture_artifacts(
                                plan, config.screenshots_dir
                            )
                            retry_result = capture_engine.execute(
                                plan, config.screenshots_dir
                            )
                            collect_capture_result(
                                plan, retry_result, allow_defer=False
                            )

                if scenario_mode:
                    capture_log(f"capture mode=scenario workers=1 plans={len(plans)}")
                    for plan in plans:
                        scenario = graph.scenarios[plan.scenario]
                        capture_log(
                            "scenario txn start "
                            f"scenario={plan.scenario} route={plan.route}"
                        )
                        with scenario_transaction(session):
                            seeded_before = seeded
                            if agentic and (
                                seed_strategy == "all_pages" or scenario.goal
                            ):
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
                                    fallback=scenario.seed.compile()
                                    if scenario.seed
                                    else None,
                                    warnings=warnings,
                                )
                                if seed_plan is not None:
                                    seeded += executor.execute(
                                        seed_plan
                                    ).objects_created
                                    capture_log(
                                        "scenario seed executed "
                                        f"scenario={plan.scenario} "
                                        "mode=agentic "
                                        f"created={seeded - seeded_before}"
                                    )
                                else:
                                    capture_log(
                                        "scenario seed skipped "
                                        f"scenario={plan.scenario} "
                                        "mode=agentic reason=no-plan"
                                    )
                            elif scenario.seed:
                                seed_plan = validator.validate(scenario.seed.compile())
                                seeded += executor.execute(seed_plan).objects_created
                                capture_log(
                                    "scenario seed executed "
                                    f"scenario={plan.scenario} "
                                    "mode=deterministic "
                                    f"created={seeded - seeded_before}"
                                )
                            else:
                                capture_log(
                                    "scenario seed skipped "
                                    f"scenario={plan.scenario} reason=no-seed"
                                )

                            capture_result = capture_engine.execute(
                                plan, config.screenshots_dir
                            )
                            capture_log(
                                "scenario capture result "
                                f"scenario={plan.scenario} "
                                f"backend={capture_result.backend_used} "
                                f"skipped={capture_result.skipped} "
                                f"created={len(capture_result.created_paths)}"
                            )
                            collect_capture_result(plan, capture_result)
                        capture_log(
                            "scenario txn end "
                            f"scenario={plan.scenario} rollback=applied"
                        )
                else:
                    capture_log(
                        "SCENARIO_MODE disabled: seed execution is computed "
                        "but database writes are skipped."
                    )
                    backend_plans = [
                        plan for plan in plans if plan.route_source == "backend"
                    ]
                    frontend_plans = [
                        plan for plan in plans if plan.route_source == "frontend"
                    ]

                    if backend_plans:
                        if capture_workers > 1:
                            capture_log(
                                "capture mode=parallel "
                                f"route_source=backend workers={capture_workers} "
                                f"plans={len(backend_plans)}"
                            )
                        else:
                            capture_log(
                                "capture mode=sequential "
                                f"route_source=backend workers=1 "
                                f"plans={len(backend_plans)}"
                            )
                    if frontend_plans:
                        if capture_workers > 1:
                            self.stdout.write(
                                self.style.WARNING(
                                    "Frontend capture remains sequential even when "
                                    "CAPTURE_WORKERS>1 to avoid login/session races "
                                    "and unstable SPA render timing."
                                )
                            )
                        capture_log(
                            "capture mode=sequential "
                            f"route_source=frontend workers=1 "
                            f"plans={len(frontend_plans)}"
                        )
                        capture_log(
                            "frontend sequential mode reason="
                            "shared-auth/session stability and consistent SPA hydration"
                        )

                    for plan in plans:
                        scenario = graph.scenarios[plan.scenario]
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
                                fallback=scenario.seed.compile()
                                if scenario.seed
                                else None,
                                warnings=warnings,
                            )
                            if seed_plan is not None:
                                seeded += executor.execute(seed_plan).objects_created
                        elif scenario.seed:
                            seed_plan = validator.validate(scenario.seed.compile())
                            seeded += executor.execute(seed_plan).objects_created

                    if backend_plans:
                        execute_with_deferred_retries(backend_plans, capture_workers)
                    if frontend_plans:
                        execute_with_deferred_retries(frontend_plans, 1)
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
        manifest["capture"]["login_failed_pages"] = login_failed_pages
        manifest["capture"]["fallback_pages"] = fallback_pages
        manifest["capture"]["issue_skipped_pages"] = issue_skipped_pages
        manifest["capture"]["issue_skipped_by_reason"] = issue_skipped_by_reason
        manifest["capture"]["login_failed_details"] = login_failed_details
        manifest["capture"]["fallback_details"] = fallback_details
        manifest["capture"]["issue_skipped_details"] = issue_skipped_details
        (config.output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        report_path = ReportBuilder().build(
            config.report_dir, successful_plans, manifest=manifest
        )
        pdf_path: Path | None = None
        if options.get("pdf"):
            try:
                pdf_path = ReportBuilder().build_pdf(
                    config.report_dir,
                    [Path(path) for path in created],
                )
            except RuntimeError as exc:
                warnings.warn(str(exc))
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
        self.stdout.write(
            self.style.WARNING(
                "Capture quality: "
                "login_failed_pages="
                f"{login_failed_pages}, fallback_pages={fallback_pages}, "
                f"issue_skipped_pages={issue_skipped_pages}"
            )
        )
        self.stdout.write(self.style.SUCCESS(f"Report written to {report_path}"))
        if options.get("pdf"):
            if pdf_path is not None:
                self.stdout.write(
                    self.style.SUCCESS(f"PDF report written to {pdf_path}")
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "PDF report was requested but no screenshots were available."
                    )
                )
        self.stdout.write(self.style.SUCCESS(f"Archive written to {archive_path}"))
        emit_total_duration()


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


def _with_route_source_prefix(
    output_path: str, route_source: str, split_devices: bool
) -> str:
    if split_devices:
        prefix, _, tail = output_path.partition("/")
        if prefix in {"mobile", "desktop"} and tail:
            return f"{prefix}/{route_source}/{tail}"
    return f"{route_source}/{output_path}"


def _collapse_plans_for_non_scenario_mode(
    plans: list[CapturePlan],
) -> list[CapturePlan]:
    selected: dict[tuple[str, str], CapturePlan] = {}
    for plan in plans:
        key = (plan.route_source.lower(), (plan.route_path or plan.route).lower())
        current = selected.get(key)
        if current is None or _plan_rank(plan) < _plan_rank(current):
            selected[key] = plan
    return sorted(
        selected.values(),
        key=lambda item: (
            item.module,
            item.route_source,
            item.route_path or item.route,
            item.scenario,
        ),
    )


def _plan_rank(plan: CapturePlan) -> tuple[int, str]:
    if plan.scenario.endswith(".default"):
        return (0, plan.scenario)
    if plan.scenario.endswith(".empty"):
        return (1, plan.scenario)
    return (2, plan.scenario)
