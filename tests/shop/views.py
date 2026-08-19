from django.http import HttpResponse
from django.views import View


class DashboardView(View):
    def get(self, request):
        return HttpResponse("dashboard")


class OrdersView(View):
    def get(self, request):
        return HttpResponse("orders")


class AdminOrdersView(View):
    def get(self, request):
        return HttpResponse("admin orders")
