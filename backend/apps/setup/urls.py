from django.contrib import admin
from django.urls import path

from . import views

urlpatterns = [
    path("setup/", admin.site.admin_view(views.wizard), name="setup"),
    path("setup/later/", admin.site.admin_view(views.later), name="setup_later"),
]
