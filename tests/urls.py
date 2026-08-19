from django.urls import path

from tests.shop.views import AdminOrdersView, DashboardView, OrdersView


urlpatterns = [
    path("dashboard/", DashboardView.as_view(), name="dashboard"),
    path("orders/", OrdersView.as_view(), name="orders"),
    path("admin/orders/", AdminOrdersView.as_view(), name="admin_orders"),
    path("config/", DashboardView.as_view()),
]
