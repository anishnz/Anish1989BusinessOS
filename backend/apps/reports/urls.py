from django.urls import path

from . import api

urlpatterns = [path("dashboard/", api.DashboardView.as_view(), name="api_dashboard")]
