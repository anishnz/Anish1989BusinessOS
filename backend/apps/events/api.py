"""
Enquiries API (task 3.1).

GET   /api/events/enquiries/               list (status, q = name, phone, email or #number); counts per status   events.view
POST  /api/events/enquiries/               staff add an enquiry {details..., "customer": id}                    events.create
POST  /api/events/enquiries/from-chat/     {"conversation": id}: "Make enquiry" in the inbox                     events.create + crm.view
GET   /api/events/enquiries/<id>/          one enquiry with its history and what a quote still needs            events.view
PATCH /api/events/enquiries/<id>/          change details                                                       events.edit
POST  /api/events/enquiries/<id>/status/   {"status": "lost", "reason": "..."}                                  events.edit
POST  /api/events/enquiries/<id>/notes/    {"text": "..."}                                                      events.edit
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.apihelpers import Pages
from apps.customers.models import Customer
from apps.rbac import policy
from apps.rbac.permissions import ModulePermission

from . import services
from .models import Enquiry, EnquiryActivity

S = Enquiry.Status


def _error(exc: DjangoValidationError) -> Response:
    if hasattr(exc, "message_dict"):
        fields = {k: " ".join(v) for k, v in exc.message_dict.items()}
        return Response({"detail": " ".join(fields.values()), "fields": fields}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)


class ActivitySerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = EnquiryActivity
        fields = ["id", "kind", "kind_label", "text", "by_email", "created_at"]


class EnquirySerializer(serializers.ModelSerializer):
    name = serializers.CharField(read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    source_label = serializers.CharField(source="get_source_display", read_only=True)
    event_type_label = serializers.CharField(source="get_event_type_display", read_only=True)

    class Meta:
        model = Enquiry
        fields = ["id", "name", "status", "status_label", "source", "source_label", "event_type", "event_type_label",
                  "event_date", "start_time", "guests", "budget", "customer", "conversation", "created_at", "updated_at"]


class EnquiryDetailSerializer(EnquirySerializer):
    activities = ActivitySerializer(many=True, read_only=True)
    missing = serializers.SerializerMethodField()

    class Meta(EnquirySerializer.Meta):
        fields = EnquirySerializer.Meta.fields + [
            "contact_name", "contact_phone", "contact_email", "end_time", "venue", "menu", "dietary_needs", "message",
            "lost_reason", "status_changed_at", "activities", "missing"]

    def get_missing(self, obj):
        return services.missing(obj)


class _Base(APIView):
    permission_classes = [ModulePermission]
    permission_module = "events"


def _detail(enquiry: Enquiry) -> dict:
    enquiry = Enquiry.objects.select_related("customer").prefetch_related("activities").get(pk=enquiry.pk)
    return EnquiryDetailSerializer(enquiry).data


class EnquiryList(_Base):
    def get(self, request):
        rows = Enquiry.objects.select_related("customer")
        q = (request.query_params.get("q") or "").strip()
        if q:
            number = q.lstrip("#")
            condition = Q(contact_name__icontains=q) | Q(contact_email__icontains=q) | Q(customer__name__icontains=q)
            digits = "".join(ch for ch in q if ch.isdigit())
            if len(digits) >= 4:
                condition |= Q(contact_phone__contains=digits.lstrip("0"))
            if number.isdigit():
                condition |= Q(pk=int(number))
            rows = rows.filter(condition)
        counts = {row["status"]: row["n"] for row in rows.values("status").annotate(n=Count("id")).order_by()}
        wanted = request.query_params.get("status") or ""
        if wanted == "open":
            rows = rows.filter(status__in=[S.NEW, S.CONTACTED, S.QUOTED])
        elif wanted:
            if wanted not in S.values:
                return Response({"detail": "Unknown status."}, status=status.HTTP_400_BAD_REQUEST)
            rows = rows.filter(status=wanted)
        pages = Pages()
        page = pages.paginate_queryset(rows.order_by("-created_at", "-id"), request, view=self)
        response = pages.get_paginated_response(EnquirySerializer(page, many=True).data)
        response.data["counts"] = {s: counts.get(s, 0) for s in S.values}
        response.data["statuses"] = [{"value": v, "label": label} for v, label in S.choices]
        response.data["event_types"] = [{"value": v, "label": label} for v, label in Enquiry.EventType.choices]
        return response

    def post(self, request):
        customer = None
        if request.data.get("customer"):
            customer = Customer.objects.filter(pk=request.data.get("customer"), is_anonymised=False).first()
            if customer is None:
                return Response({"detail": "Customer not found."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            enquiry = services.create(request.data, source=Enquiry.Source.STAFF, actor=request.user, customer=customer)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(_detail(enquiry), status=status.HTTP_201_CREATED)


class FromChat(_Base):
    def post(self, request):
        from apps.inbox.models import Conversation

        if not policy.require(request.user, "crm.view", request=request._request).allowed:
            return Response({"detail": "You do not have permission to do this."}, status=status.HTTP_403_FORBIDDEN)
        conversation = Conversation.objects.select_related("customer").filter(pk=request.data.get("conversation")).first()
        if conversation is None:
            return Response({"detail": "Chat not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            enquiry = services.from_conversation(conversation, actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(_detail(enquiry), status=status.HTTP_201_CREATED)


class EnquiryDetail(_Base):
    def get(self, request, pk):
        return Response(_detail(get_object_or_404(Enquiry, pk=pk)))

    def patch(self, request, pk):
        enquiry = get_object_or_404(Enquiry, pk=pk)
        try:
            services.update(enquiry, request.data, actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(_detail(enquiry))


class EnquiryStatus(_Base):
    permission_actions = {"POST": "edit"}

    def post(self, request, pk):
        enquiry = get_object_or_404(Enquiry, pk=pk)
        try:
            services.set_status(enquiry, str(request.data.get("status", "")), reason=str(request.data.get("reason") or ""), actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(_detail(enquiry))


class EnquiryNote(_Base):
    permission_actions = {"POST": "edit"}

    def post(self, request, pk):
        enquiry = get_object_or_404(Enquiry, pk=pk)
        try:
            services.add_note(enquiry, str(request.data.get("text") or ""), actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(_detail(enquiry), status=status.HTTP_201_CREATED)
