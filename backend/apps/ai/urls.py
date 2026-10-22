from django.urls import path

from . import api

urlpatterns = [
    path("chats/<int:pk>/", api.ChatAI.as_view(), name="api_ai_chat"),
    path("waiting/", api.WaitingChats.as_view(), name="api_ai_waiting"),
]
