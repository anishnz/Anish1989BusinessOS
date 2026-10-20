from django.contrib import admin
from django.urls import path

from . import views

web_urlpatterns = [
    path("system-check/", admin.site.admin_view(views.check_page), name="system_check"),
    path("system-check/<int:pk>/", admin.site.admin_view(views.run_page), name="system_check_run"),
]
api_urlpatterns = [
    path("", views.CheckStatusView.as_view(), name="api_system_check"),
    path("run/", views.CheckRunView.as_view(), name="api_system_check_run"),
]
