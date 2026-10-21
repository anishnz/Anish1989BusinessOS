from django.urls import path

from . import views

urlpatterns = [
    path("guide/", views.home, name="guide"),
    path("guide/search/", views.search, name="guide_search"),
    path("guide/images/<str:name>", views.image, name="guide_image"),
    path("guide/<slug:slug>/", views.chapter, name="guide_chapter"),
]
