from django.contrib import admin
from django.urls import path

from . import views

web_urlpatterns = [
    path("backups/", admin.site.admin_view(views.backups_page), name="backups"),
    path("backups/google/finish/", admin.site.admin_view(views.google_finish), name="backups_google_finish"),
    path("backups/tool/", admin.site.admin_view(views.decrypt_tool), name="backups_tool"),
]
api_urlpatterns = [
    path("", views.BackupStatusView.as_view(), name="api_backups"),
    path("run/", views.BackupRunView.as_view(), name="api_backups_run"),
]
# Platform site only: Google's return address after "Connect Google Drive".
public_urlpatterns = [
    path("oauth/google/callback/", views.google_callback, name="google_oauth_callback"),
]
