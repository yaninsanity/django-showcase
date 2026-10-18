from django_showcase.capture.compiler import CapturePlanCompiler
from django_showcase.discovery.models import inspect_models
from django_showcase.discovery.urls import discover_routes
from django_showcase.discovery.views import inspect_views
from django_showcase.scenario.planner import PlannerInputs, ScenarioPlanner


def test_planner_generates_status_and_staff_scenarios(settings):
    routes = discover_routes()
    graph = ScenarioPlanner().build_graph(
        PlannerInputs(
            routes=routes,
            views=inspect_views(routes),
            models=inspect_models(),
            max_scenarios_per_module=8,
            max_choices_per_field=4,
        )
    )

    assert "orders.orders.default" in graph.scenarios
    assert any(
        scenario_id.startswith("config.unnamed_config")
        for scenario_id in graph.scenarios
    )
    assert "orders.orders.empty" in graph.scenarios
    assert "admin.admin_orders.permission_denied" in graph.scenarios
    assert "orders.orders.pending" in graph.scenarios
    assert "orders.orders.failed" in graph.scenarios
    assert "orders.orders.high_volume" in graph.scenarios
    assert graph.module_candidate_counts["orders"] >= 5

    plans = CapturePlanCompiler().compile(graph)
    pending = next(plan for plan in plans if plan.scenario == "orders.orders.pending")
    assert pending.estimated_objects == 3
    assert len(pending.captures) == 2
    assert pending.route_path == "/orders/"
