"""URLs for the platform site (public schema): Super Admin and platform pages."""
from django.contrib import admin
from django.urls import path

from apps.accounts import platform_pages
from apps.backups.urls import public_urlpatterns as backup_public_urlpatterns
from apps.tenants import platform_pages as tenant_pages

from .urls_shared import shared_urlpatterns

# Super Admin pages (platform site only). admin_view: staff login + MFA required.
platform_urlpatterns = [
    path("platform/people/", admin.site.admin_view(platform_pages.people_index), name="platform_people"),
    path("platform/people/<slug:schema>/", admin.site.admin_view(platform_pages.people_list), name="platform_people_list"),
    path("platform/people/<slug:schema>/<int:user_id>/", admin.site.admin_view(platform_pages.person_detail), name="platform_person"),
    path("platform/businesses/<slug:schema>/addresses/", admin.site.admin_view(tenant_pages.addresses), name="platform_addresses"),
]

urlpatterns = [
    *platform_urlpatterns,
    *backup_public_urlpatterns,
    *shared_urlpatterns,
]
