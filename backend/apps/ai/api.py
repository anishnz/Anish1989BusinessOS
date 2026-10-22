"""
AI assistant API for the staff app (task 2.4). Permissions use the CRM module, like the inbox.

GET  /api/ai/chats/<conversation id>/     is the AI answering this chat, or are staff?   crm.view
POST /api/ai/chats/<conversation id>/     {"answer": true}  let the AI answer again      crm.edit
                                          {"answer": false} I will answer (assigns the chat to me, task 2.5)
GET  /api/ai/waiting/                     chats handed over that nobody picked up yet    crm.view
                                          ({"count": n, "results": [oldest first, at most 50]})
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
            conversation.assigned_to = request.user  # D-150: the chat shows who is handling it
            conversation.save(update_fields=["assigned_to"])
        return Response(state(conversation))


def waiting_row(chat: AIChat) -> dict:
    conversation = chat.conversation
    customer = conversation.customer
    return {"conversation": conversation.pk, "customer_name": customer.name if customer else "", "customer_phone": customer.phone if customer else "",
            "reason": chat.handover_reason, "since": chat.handed_over_at, "unread_count": conversation.unread_count}


class WaitingChats(APIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    permission_actions = {"GET": "view"}

    def get(self, request):
        chats = agent.waiting_chats()
        return Response({"count": chats.count(), "results": [waiting_row(c) for c in chats[:50]]})
