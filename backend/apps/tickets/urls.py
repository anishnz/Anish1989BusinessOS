from django.contrib import admin
from django.urls import path

from . import views

web_urlpatterns = [
    path("tickets/", admin.site.admin_view(views.ticket_list), name="ticket_list"),
    path("tickets/new/", admin.site.admin_view(views.ticket_new), name="ticket_new"),
    path("tickets/<int:pk>/", admin.site.admin_view(views.ticket_detail), name="ticket_detail"),
    path("tickets/from-check/<int:run_id>/", admin.site.admin_view(views.from_check), name="ticket_from_check"),
    path("tickets/from-backup/<int:run_id>/", admin.site.admin_view(views.from_backup), name="ticket_from_backup"),
]
api_urlpatterns = [
    path("", views.TicketListApi.as_view(), name="api_tickets"),
    path("<int:pk>/", views.TicketDetailApi.as_view(), name="api_ticket"),
    path("<int:pk>/comments/", views.TicketCommentApi.as_view(), name="api_ticket_comments"),
]
