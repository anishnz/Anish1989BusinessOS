from django.urls import path

from . import api

urlpatterns = [
    path("conversations/", api.ConversationList.as_view(), name="api_conversations"),
    path("conversations/<int:pk>/", api.ConversationDetail.as_view(), name="api_conversation"),
    path("conversations/<int:pk>/read/", api.ConversationRead.as_view(), name="api_conversation_read"),
    path("conversations/<int:pk>/reply/", api.ConversationReply.as_view(), name="api_conversation_reply"),
    path("conversations/<int:pk>/template/", api.ConversationTemplate.as_view(), name="api_conversation_template"),
    path("conversations/<int:pk>/assign/", api.ConversationAssign.as_view(), name="api_conversation_assign"),
    path("conversations/<int:pk>/close/", api.ConversationClose.as_view(), name="api_conversation_close"),
    path("start/", api.StartConversation.as_view(), name="api_conversation_start"),
]
