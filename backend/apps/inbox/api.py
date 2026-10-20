"""
Inbox API (permissions use the CRM module: conversations are with customers).

GET  /api/inbox/conversations/                  list (filters: status=open|closed, mine=true, unread=true, q)  crm.view
GET  /api/inbox/conversations/<id>/             one conversation with its latest 200 messages                 crm.view
POST /api/inbox/conversations/<id>/read/        mark as read                                                   crm.view
POST /api/inbox/conversations/<id>/reply/       {"text": "..."} (within 24 hours of the customer's message)    crm.edit
POST /api/inbox/conversations/<id>/template/    {"name", "language", "params": [], "category"}                 crm.edit
POST /api/inbox/conversations/<id>/assign/      {"user": <id> or null}                                         crm.assign
POST /api/inbox/conversations/<id>/close/       {"closed": true}                                               crm.edit
POST /api/inbox/start/                          {"customer": <id>, "name", "language", "params", "category"}   crm.edit
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.apihelpers import Pages, as_bool
from apps.customers.models import Customer
from apps.rbac.permissions import ModulePermission

from . import services
from .models import Conversation, Message


class MessageSerializer(serializers.ModelSerializer):
    sent_by_email = serializers.CharField(source="sent_by.email", default="", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "direction", "kind", "text", "media_id", "template_name", "status", "error", "sent_by_email", "provider_timestamp", "created_at"]


class ConversationSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.name", default="", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", default="", read_only=True)
    assigned_to_email = serializers.CharField(source="assigned_to.email", default="", read_only=True)
    can_reply_freely = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "channel", "customer", "customer_name", "customer_phone", "status", "assigned_to", "assigned_to_email",
            "unread_count", "last_message_at", "last_inbound_at", "last_message_preview", "can_reply_freely",
        ]

    def get_can_reply_freely(self, obj):
        return services.can_reply_freely(obj)


def _error(exc):
    return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)


def _detail(conversation):
    data = ConversationSerializer(conversation).data
    latest = list(conversation.messages.select_related("sent_by").order_by("-created_at", "-id")[:200])
    data["messages"] = MessageSerializer(reversed(latest), many=True).data
    return data


class ConversationList(generics.ListAPIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    serializer_class = ConversationSerializer
    pagination_class = Pages

    def get_queryset(self):
        params = self.request.query_params
        qs = Conversation.objects.select_related("customer", "assigned_to").exclude(external_id="", messages__isnull=True)
        if params.get("status") in Conversation.Status.values:
            qs = qs.filter(status=params["status"])
        if as_bool(params.get("mine")):
            qs = qs.filter(assigned_to=self.request.user)
        if as_bool(params.get("unread")):
            qs = qs.filter(unread_count__gt=0)
        q = (params.get("q") or "").strip()
        if q:
            digits = "".join(ch for ch in q if ch.isdigit()).lstrip("0")
            condition = Q(customer__name__icontains=q)
            if len(digits) >= 4:
                condition |= Q(external_id__contains=digits)
            qs = qs.filter(condition)
        return qs.distinct()


class ConversationDetail(APIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"

    def get(self, request, pk):
        return Response(_detail(get_object_or_404(Conversation.objects.select_related("customer", "assigned_to"), pk=pk)))


class _Action(APIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    permission_actions = {"POST": "edit"}

    def run(self, pk, func):
        conversation = get_object_or_404(Conversation, pk=pk)
        try:
            func(conversation)
        except DjangoValidationError as exc:
            return _error(exc)
        conversation.refresh_from_db()
        return Response(_detail(conversation))


class ConversationRead(_Action):
    permission_actions = {"POST": "view"}

    def post(self, request, pk):
        return self.run(pk, services.mark_read)


class ConversationReply(_Action):
    def post(self, request, pk):
        return self.run(pk, lambda c: services.send_text(c, str(request.data.get("text") or ""), actor=request.user))


def _template_args(data):
    params = data.get("params") or []
    if not isinstance(params, list):
        raise DjangoValidationError("params must be a list.")
    return {
        "name": str(data.get("name") or ""), "language": str(data.get("language") or "en"),
        "params": params, "category": str(data.get("category") or "utility"),
    }


class ConversationTemplate(_Action):
    def post(self, request, pk):
        return self.run(pk, lambda c: services.send_template(c, **_template_args(request.data), actor=request.user))


class ConversationAssign(_Action):
    permission_actions = {"POST": "assign"}

    def post(self, request, pk):
        user_id = request.data.get("user")
        user = None
        if user_id not in (None, ""):
            user = get_user_model().objects.filter(pk=user_id).first()
            if user is None:
                return Response({"detail": "Unknown user."}, status=status.HTTP_400_BAD_REQUEST)
        return self.run(pk, lambda c: services.assign(c, user, actor=request.user))


class ConversationClose(_Action):
    def post(self, request, pk):
        closed = as_bool(request.data.get("closed"))
        return self.run(pk, lambda c: services.set_closed(c, True if closed is None else closed, actor=request.user))


class StartConversation(APIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    permission_actions = {"POST": "edit"}

    def post(self, request):
        customer = get_object_or_404(Customer, pk=request.data.get("customer") or 0)
        try:
            conversation = services.conversation_for_customer(customer)
            services.send_template(conversation, **_template_args(request.data), actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        conversation.refresh_from_db()
        return Response(_detail(conversation), status=status.HTTP_201_CREATED)
