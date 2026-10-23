from django.urls import path

from . import api, views

api_urlpatterns = [
    path("", api.WebsiteState.as_view(), name="api_website"),
    path("draft/", api.DraftSave.as_view(), name="api_website_draft"),
    path("publish/", api.Publish.as_view(), name="api_website_publish"),
    path("versions/", api.Versions.as_view(), name="api_website_versions"),
    path("versions/<int:number>/restore/", api.Restore.as_view(), name="api_website_restore"),
    path("generate/", api.Generate.as_view(), name="api_website_generate"),
]

# The public page and its helpers (business sites only)
page_urlpatterns = [
    path("", views.home, name="website_home"),
    path("robots.txt", views.robots, name="website_robots"),
    path("sitemap.xml", views.sitemap, name="website_sitemap"),
    path("website/preview/", views.preview, name="website_preview"),
]
