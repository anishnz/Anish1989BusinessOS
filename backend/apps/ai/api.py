"""
AI assistant API for the staff app (task 2.4). Permissions use the CRM module, like the inbox.

GET  /api/ai/chats/<conversation id>/     is the AI answering this chat, or are staff?   crm.view
POST /api/ai/chats/<conversation id>/     {"answer": true}  let the AI answer again      crm.edit
                                          {"answer": false} staff take over the chat
"""
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import audit
from apps.core.apihelpers import as_bool
from apps.inbox.models import Conversation
from apps.rbac.permissions import ModulePermission

from . import agent
from .models import AIChat


def state(conversation: Conversation) -> dict:
    chat = AIChat.objects.filter(conversation=conversation).select_related("order").first() or AIChat(conversation=conversation)
    on = agent.is_on()
    why = agent.staff_handling(conversation, chat) if on else ""
    return {"ai_on": on, "state": "off" if not on else "staff" if why else "answering", "reason": why,
            "since": chat.handed_over_at, "order_number": chat.order.number if chat.order_id else None}


class ChatAI(APIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    permission_actions = {"GET": "view", "POST": "edit"}

    def get(self, request, pk):
        return Response(state(get_object_or_404(Conversation, pk=pk)))

    def post(self, request, pk):
        conversation = get_object_or_404(Conversation, pk=pk)
        wanted = as_bool(request.data.get("answer"))
        if wanted is None:
            return Response({"detail": "Send answer: true (let the AI answer) or false (staff take over)."}, status=400)
        chat, _ = AIChat.objects.get_or_create(conversation=conversation)
        if wanted:
            chat.handed_over_at, chat.handover_reason, chat.told_customer_at = None, "", None
            chat.resumed_at = timezone.now()
            chat.save()
            if conversation.assigned_to_id:
                conversation.assigned_to = None
                conversation.save(update_fields=["assigned_to"])
            audit("ai.resumed", target=conversation, actor=request.user)
        else:
            agent.hand_over(chat, f"Taken over by {request.user.email}", tell=False, actor=request.user)
        return Response(state(conversation))
