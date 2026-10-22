"""
Orders API.

GET    /api/orders/                    list (filters: status, open, customer, date=YYYY-MM-DD, q=number)  orders.view
POST   /api/orders/                    create a draft                                                    orders.create
GET    /api/orders/<id>/               one order with lines and history                                  orders.view
PATCH  /api/orders/<id>/               change customer, notes, channel, lines, pickup or delivery        orders.edit
DELETE /api/orders/<id>/               delete a draft                                                    orders.delete
POST   /api/orders/<id>/status/        {"to": "confirmed", "note": ""}                                   orders.edit
POST   /api/orders/<id>/weights/       {"weights": {"<line id>": "1.08"}}                                orders.edit
POST   /api/orders/<id>/payment/       {"paid": true, "method": "cash"}                                  orders.edit
POST   /api/orders/<id>/reorder/       order again: a new draft at today's prices (+ "left_out")       orders.create
GET    /api/orders/export/             CSV, one row per line (date_from, date_to)                        orders.export
GET    /api/orders/board/              the live order board: today's and late orders (?tomorrow=1 adds tomorrow)  orders.view
GET    /api/orders/fulfilment/         pickup and delivery settings and the active delivery areas        orders.view
GET    /api/orders/slots/              ?kind=pickup|delivery&date=YYYY-MM-DD&order=<id>: that day's slots  orders.view
GET    /api/orders/delivery-areas/find/ ?postcode=&suburb=&address=: the matching area (or null)        orders.view

Lines are sent as [{"product": 5, "quantity": "1.5", "note": ""}]. Prices
always come from the product; a price in the request is ignored.

Pickup or delivery: "fulfilment" ("pickup" or "delivery"), "due_at" (the
pickup time or the start of the delivery window), and for delivery
"delivery_address", "delivery_suburb", "delivery_postcode" and optionally
"delivery_area" (found from the postcode or suburb when left out). The
delivery fee always comes from the area. "warnings" lists the slot, area and
minimum-order rules the order breaks (staff may still book it, D-121).

WhatsApp messages (task 2.3): one order also has "messages" (what the
customer was sent about it, and their Yes or No answers). Moving an order to
"awaiting_confirmation" or "final_price_sent" sends the customer a question.
"""
from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import audit
from apps.core import csvtools
from apps.core.apihelpers import Pages
from apps.core.apihelpers import as_bool
from apps.customers.models import Customer
from apps.fulfilment import services as fulfilment
from apps.fulfilment.models import ClosedDay, DeliveryArea, Kind
from apps.rbac.permissions import ModulePermission

from . import board, notify, services
from .models import Order, OrderEvent, OrderLine, OrderMessage


class LineSerializer(serializers.ModelSerializer):
    effective_quantity = serializers.DecimalField(max_digits=10, decimal_places=3, read_only=True)

    class Meta:
        model = OrderLine
        fields = ["id", "product", "product_name", "unit", "unit_price", "gst_applies", "quantity", "final_quantity", "effective_quantity", "note", "line_total"]


class EventSerializer(serializers.ModelSerializer):
    actor_email = serializers.CharField(source="actor.email", default="", read_only=True)

    class Meta:
        model = OrderEvent
        fields = ["from_status", "to_status", "note", "actor_email", "at"]


class OrderSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="status_text", read_only=True)
    customer_name = serializers.CharField(source="customer.name", default="", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", default="", read_only=True)
    delivery_area_name = serializers.CharField(source="delivery_area.name", default="", read_only=True)
    due_text = serializers.SerializerMethodField()
    lines = LineSerializer(many=True, read_only=True)
    next_statuses = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "number", "status", "status_label", "next_statuses", "channel", "customer", "customer_name", "customer_phone",
            "fulfilment", "due_at", "due_until", "due_text", "delivery_address", "delivery_suburb", "delivery_postcode",
            "delivery_area", "delivery_area_name", "delivery_fee",
            "notes", "lines", "estimated_total", "total", "gst_total", "is_paid", "payment_method", "paid_at",
            "confirmed_at", "completed_at", "cancelled_at", "created_at", "updated_at",
        ]

    def get_next_statuses(self, obj):
        return services.allowed_moves(obj)

    def get_due_text(self, obj):
        return services.due_text(obj)


class MessageSerializer(serializers.ModelSerializer):
    label = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()

    class Meta:
        model = OrderMessage
        fields = ["id", "kind", "label", "status", "result", "via", "is_open", "answer", "created_at", "sent_at", "answered_at"]

    def get_label(self, obj):
        return notify.label(obj)

    def get_result(self, obj):
        return notify.status_text(obj)


class OrderDetailSerializer(OrderSerializer):
    events = EventSerializer(many=True, read_only=True)
    warnings = serializers.SerializerMethodField()
    messages = serializers.SerializerMethodField()

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ["events", "warnings", "messages"]

    def get_messages(self, obj):
        return MessageSerializer(obj.messages.select_related("inbox_message"), many=True).data

    def get_warnings(self, obj):
        return services.warnings(obj)


class LineInputSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


class OrderInputSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_archived=False), required=False, allow_null=True)
    channel = serializers.ChoiceField(choices=Order.Channel.choices, required=False)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    fulfilment = serializers.ChoiceField(choices=Kind.choices, required=False)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    delivery_address = serializers.CharField(required=False, allow_blank=True, max_length=200)
    delivery_suburb = serializers.CharField(required=False, allow_blank=True, max_length=100)
    delivery_postcode = serializers.CharField(required=False, allow_blank=True, max_length=4)
    delivery_area = serializers.PrimaryKeyRelatedField(queryset=DeliveryArea.objects.all(), required=False, allow_null=True)
    lines = LineInputSerializer(many=True, required=False)


def _lines(data):
    return [services.LineInput(product_id=l["product"], quantity=l["quantity"], note=l.get("note", "")) for l in data]


def _error(exc: DjangoValidationError):
    return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)


def _local_day(value: str):
    day = datetime.strptime(value, "%Y-%m-%d").date()
    tz = timezone.get_current_timezone()
    return timezone.make_aware(datetime.combine(day, time.min), tz), timezone.make_aware(datetime.combine(day, time.max), tz)


class OrderList(generics.ListCreateAPIView):
    permission_classes = [ModulePermission]
    permission_module = "orders"
    serializer_class = OrderSerializer
    pagination_class = Pages

    def get_queryset(self):
        params = self.request.query_params
        qs = Order.objects.select_related("customer", "delivery_area").prefetch_related("lines")
        if params.get("status"):
            qs = qs.filter(status__in=params["status"].split(","))
        open_only = as_bool(params.get("open"))
        if open_only is not None:
            from .models import CLOSED_STATUSES

            qs = qs.exclude(status__in=CLOSED_STATUSES) if open_only else qs.filter(status__in=CLOSED_STATUSES)
        if params.get("customer"):
            qs = qs.filter(customer_id=params["customer"]) if params["customer"].isdigit() else qs.none()
        if params.get("date"):
            try:
                start, end = _local_day(params["date"])
            except ValueError:
                return qs.none()
            qs = qs.filter(created_at__range=(start, end))
        q = (params.get("q") or "").strip().lstrip("#")
        if q:
            qs = qs.filter(number=int(q)) if q.isdigit() else qs.filter(customer__name__icontains=q)
        return qs

    def create(self, request, *args, **kwargs):
        data = OrderInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        details = {k: v[k] for k in services.FULFILMENT_FIELDS if k in v}
        try:
            order = services.create_order(
                lines=_lines(v.get("lines", [])), customer=v.get("customer"), channel=v.get("channel", Order.Channel.COUNTER),
                notes=v.get("notes", ""), actor=request.user, **details,
            )
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(OrderDetailSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderDetail(APIView):
    permission_classes = [ModulePermission]
    permission_module = "orders"

    def get(self, request, pk):
        order = get_object_or_404(Order.objects.select_related("customer", "delivery_area").prefetch_related("lines", "events__actor"), pk=pk)
        return Response(OrderDetailSerializer(order).data)

    def patch(self, request, pk):
        order = get_object_or_404(Order, pk=pk)
        data = OrderInputSerializer(data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        v = dict(data.validated_data)
        lines = v.pop("lines", None)
        try:
            order = services.update_order(order, lines=_lines(lines) if lines is not None else None, actor=request.user, **v)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(OrderDetailSerializer(order).data)

    def delete(self, request, pk):
        try:
            services.delete_draft(get_object_or_404(Order, pk=pk), actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)


class _OrderAction(APIView):
    permission_classes = [ModulePermission]
    permission_module = "orders"
    permission_actions = {"POST": "edit"}

    def run(self, request, pk, func):
        try:
            order = func(get_object_or_404(Order, pk=pk))
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(OrderDetailSerializer(order).data)


class OrderReorder(APIView):
    """Order again (task 2.5): a new draft with the same products at today's prices."""

    permission_classes = [ModulePermission]
    permission_module = "orders"
    permission_actions = {"POST": "create"}

    def post(self, request, pk):
        try:
            order, left_out = services.reorder(get_object_or_404(Order, pk=pk), actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response({**OrderDetailSerializer(order).data, "left_out": left_out}, status=status.HTTP_201_CREATED)


class OrderBoard(APIView):
    """The live order board for the counter and the kitchen (task 2.6). Staff move orders on with /status/."""

    permission_classes = [ModulePermission]
    permission_module = "orders"

    def get(self, request):
        return Response(board.board(tomorrow=bool(as_bool(request.query_params.get("tomorrow")))))


class OrderStatus(_OrderAction):
    def post(self, request, pk):
        return self.run(request, pk, lambda o: services.change_status(o, str(request.data.get("to", "")), actor=request.user, note=str(request.data.get("note") or "")))


class OrderWeights(_OrderAction):
    def post(self, request, pk):
        weights = request.data.get("weights")
        if not isinstance(weights, dict) or not weights:
            return Response({"detail": 'Send weights as {"<line id>": "1.08"}.'}, status=status.HTTP_400_BAD_REQUEST)
        if not all(str(k).isdigit() for k in weights):
            return Response({"detail": "Line ids must be numbers."}, status=status.HTTP_400_BAD_REQUEST)
        return self.run(request, pk, lambda o: services.set_weights(o, weights, actor=request.user))


class OrderPayment(_OrderAction):
    def post(self, request, pk):
        paid = as_bool(request.data.get("paid"))
        if paid is None:
            return Response({"detail": "Send paid: true or false."}, status=status.HTTP_400_BAD_REQUEST)
        return self.run(request, pk, lambda o: services.set_paid(o, paid, method=str(request.data.get("method") or ""), actor=request.user))


EXPORT_COLUMNS = [
    "order", "created", "status", "channel", "customer", "fulfilment", "due", "delivery_area", "delivery_fee", "product", "unit", "ordered",
    "real_weight", "unit_price", "line_total", "order_total", "gst_included", "paid", "payment_method",
]


def export_rows(queryset):
    tz = timezone.get_current_timezone()
    fmt = "%Y-%m-%d %H:%M"
    for order in queryset.select_related("customer", "delivery_area").prefetch_related("lines"):
        for line in order.lines.all():
            yield [
                order.number, timezone.localtime(order.created_at, tz).strftime(fmt), order.status, order.channel,
                order.customer.name if order.customer else "", order.fulfilment,
                timezone.localtime(order.due_at, tz).strftime(fmt) if order.due_at else "",
                order.delivery_area.name if order.delivery_area else "", order.delivery_fee,
                line.product_name, line.unit, f"{line.quantity.normalize():f}", f"{line.final_quantity.normalize():f}" if line.final_quantity else "",
                line.unit_price, line.line_total, order.total, order.gst_total, "yes" if order.is_paid else "no", order.payment_method,
            ]


class OrderExport(APIView):
    permission_classes = [ModulePermission]
    permission_module = "orders"
    permission_actions = {"GET": "export"}

    def get(self, request):
        qs = Order.objects.all()
        try:
            if request.query_params.get("date_from"):
                qs = qs.filter(created_at__gte=_local_day(request.query_params["date_from"])[0])
            if request.query_params.get("date_to"):
                qs = qs.filter(created_at__lte=_local_day(request.query_params["date_to"])[1])
        except ValueError:
            return Response({"detail": "Dates must look like 2026-10-21."}, status=status.HTTP_400_BAD_REQUEST)
        audit("orders.export", actor=request.user, metadata={"orders": qs.count()})
        return csvtools.csv_response("orders.csv", EXPORT_COLUMNS, export_rows(qs.order_by("number")))


# ---------------------------------------------------------------------------
# Pickup and delivery (task 2.1)
# ---------------------------------------------------------------------------
def _area_json(area: DeliveryArea) -> dict:
    return {"id": area.pk, "name": area.name, "fee": str(area.fee), "minimum_order": str(area.minimum_order),
            "free_over": str(area.free_over) if area.free_over is not None else None, "postcodes": area.postcode_list(),
            "suburbs": area.suburb_list()}


class FulfilmentInfo(APIView):
    permission_classes = [ModulePermission]
    permission_module = "orders"

    def get(self, request):
        s = fulfilment.current_settings()
        return Response({
            "pickup_enabled": s.pickup_enabled, "delivery_enabled": s.delivery_enabled,
            "pickup_slot_minutes": s.pickup_slot_minutes, "delivery_slot_minutes": s.delivery_slot_minutes,
            "lead_minutes": s.lead_minutes, "days_ahead": s.days_ahead,
            "areas": [_area_json(a) for a in DeliveryArea.objects.filter(is_active=True)],
        })


class FulfilmentSlots(APIView):
    """One day's slots for staff: free, full, too soon or past, so they can pick one or type another time."""

    permission_classes = [ModulePermission]
    permission_module = "orders"

    def get(self, request):
        params = request.query_params
        kind = params.get("kind", Kind.PICKUP)
        if kind not in Kind.values:
            return Response({"detail": "kind must be pickup or delivery."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            day = date.fromisoformat(params["date"]) if params.get("date") else timezone.localdate()
        except ValueError:
            return Response({"detail": "Dates must look like 2026-10-21."}, status=status.HTTP_400_BAD_REQUEST)
        exclude = int(params["order"]) if str(params.get("order", "")).isdigit() else None
        s = fulfilment.current_settings()
        now = timezone.now()
        earliest = now + timedelta(minutes=s.lead_minutes)
        closed = ClosedDay.objects.filter(date=day).first()
        found = []
        for slot in fulfilment.slots(kind, day, 1, exclude_order_id=exclude):
            item = slot.as_json()
            item["past"] = slot.start < now
            item["too_soon"] = not item["past"] and slot.start < earliest
            found.append(item)
        return Response({
            "kind": kind, "date": day.isoformat(), "enabled": s.enabled(kind),
            "closed": bool(closed), "closed_reason": closed.reason if closed else "", "slots": found,
        })


class FindDeliveryArea(APIView):
    permission_classes = [ModulePermission]
    permission_module = "orders"

    def get(self, request):
        params = request.query_params
        area = fulfilment.find_area(postcode=params.get("postcode", ""), suburb=params.get("suburb", ""), address=params.get("address", ""))
        return Response({"area": _area_json(area) if area else None})
