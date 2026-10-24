from django_showcase.capture.compiler import CapturePlanCompiler
from django_showcase.discovery.models import FieldMetadata, ModelMetadata
from django_showcase.discovery.urls import RouteInfo, normalize_route_pattern
from django_showcase.discovery.views import ViewMetadata
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
    outputs = {capture.output_path for capture in pending.captures}
    assert "desktop/orders/orders__pending.png" in outputs
    assert "mobile/orders/orders__pending.png" in outputs

    admin_default_plans = [
        plan
        for plan in plans
        if plan.module == "admin" and plan.scenario.endswith(".default")
    ]
    admin_default_outputs = {
        capture.output_path
        for plan in admin_default_plans
        for capture in plan.captures
        if capture.viewport == "desktop"
    }
    assert len(admin_default_outputs) == len(admin_default_plans)


def test_planner_handles_numeric_choices():
    planner = ScenarioPlanner()
    graph = planner.build_graph(
        PlannerInputs(
            routes=[
                RouteInfo(
                    name="orders",
                    pattern="/orders/",
                    module_id="orders",
                    view_name="OrdersView",
                )
            ],
            views=[ViewMetadata(route_name="orders", view_name="OrdersView")],
            models=[
                ModelMetadata(
                    label="shop.Order",
                    fields=[FieldMetadata(name="status", kind="IntegerField", choices=[1])],
                )
            ],
            max_scenarios_per_module=8,
            max_choices_per_field=4,
        )
    )

    assert "orders.orders.1" in graph.scenarios
    assert graph.scenarios["orders.orders.1"].title == "1"


def test_normalize_route_pattern_removes_regex_literals():
    pattern = r"^memories/current\.(?P<format>[a-z0-9]+)/?$"
    assert normalize_route_pattern(pattern) == "/memories/current.json/"
    assert normalize_route_pattern("/orders/") == "/orders/"


def test_normalize_route_pattern_replaces_django_converters_with_samples():
    pattern = "admin/avatar/avatar/<path:object_id>/change/"
    assert normalize_route_pattern(pattern) == "/admin/avatar/avatar/1/change/"


def test_normalize_route_pattern_uses_one_for_int_identifiers():
    assert normalize_route_pattern("/orders/<int:id>/") == "/orders/1/"


def test_planner_propagates_route_method_metadata():
    planner = ScenarioPlanner()
    graph = planner.build_graph(
        PlannerInputs(
            routes=[
                RouteInfo(
                    name="orders_submit",
                    pattern="/orders/submit/",
                    module_id="orders",
                    view_name="OrdersSubmitView",
                    is_get_supported=False,
                    allowed_methods=("post",),
                )
            ],
            views=[ViewMetadata(route_name="orders_submit", view_name="OrdersSubmitView")],
            models=[],
            max_scenarios_per_module=4,
            max_choices_per_field=2,
        )
    )

    scenario = graph.scenarios["orders.orders_submit.default"]
    assert scenario.params["is_get_supported"] is False
    assert scenario.params["allowed_methods"] == ["post"]
