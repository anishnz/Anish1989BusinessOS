"""
Orders API.

GET    /api/orders/                    list (filters: status, open, customer, date=YYYY-MM-DD, q=number)  orders.view
POST   /api/orders/                    create a draft                                                    orders.create
GET    /api/orders/<id>/               one order with lines and history                                  orders.view
PATCH  /api/orders/<id>/               change customer, notes, pickup time, channel, lines               orders.edit
DELETE /api/orders/<id>/               delete a draft                                                    orders.delete
POST   /api/orders/<id>/status/        {"to": "confirmed", "note": ""}                                   orders.edit
POST   /api/orders/<id>/weights/       {"weights": {"<line id>": "1.08"}}                                orders.edit
POST   /api/orders/<id>/payment/       {"paid": true, "method": "cash"}                                  orders.edit
GET    /api/orders/export/             CSV, one row per line (date_from, date_to)                        orders.export

Lines are sent as [{"product": 5, "quantity": "1.5", "note": ""}]. Prices
always come from the product; a price in the request is ignored.
"""
from datetime import datetime, time

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
from apps.rbac.permissions import ModulePermission

from . import services
from .models import Order, OrderEvent, OrderLine


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
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    customer_name = serializers.CharField(source="customer.name", default="", read_only=True)
    customer_phone = serializers.CharField(source="customer.phone", default="", read_only=True)
    lines = LineSerializer(many=True, read_only=True)
    next_statuses = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            "id", "number", "status", "status_label", "next_statuses", "channel", "customer", "customer_name", "customer_phone",
            "pickup_at", "notes", "lines", "estimated_total", "total", "gst_total", "is_paid", "payment_method", "paid_at",
            "confirmed_at", "completed_at", "cancelled_at", "created_at", "updated_at",
        ]

    def get_next_statuses(self, obj):
        return services.allowed_moves(obj)


class OrderDetailSerializer(OrderSerializer):
    events = EventSerializer(many=True, read_only=True)

    class Meta(OrderSerializer.Meta):
        fields = OrderSerializer.Meta.fields + ["events"]


class LineInputSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    quantity = serializers.DecimalField(max_digits=10, decimal_places=3)
    note = serializers.CharField(required=False, allow_blank=True, max_length=200, default="")


class OrderInputSerializer(serializers.Serializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.filter(is_archived=False), required=False, allow_null=True)
    channel = serializers.ChoiceField(choices=Order.Channel.choices, required=False)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    pickup_at = serializers.DateTimeField(required=False, allow_null=True)
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
        qs = Order.objects.select_related("customer").prefetch_related("lines")
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
        v = data.validated_data
        try:
            order = services.create_order(
                lines=_lines(v.get("lines", [])), customer=v.get("customer"), channel=v.get("channel", Order.Channel.COUNTER),
                notes=v.get("notes", ""), pickup_at=v.get("pickup_at"), actor=request.user,
            )
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(OrderDetailSerializer(order).data, status=status.HTTP_201_CREATED)


class OrderDetail(APIView):
    permission_classes = [ModulePermission]
    permission_module = "orders"

    def get(self, request, pk):
        order = get_object_or_404(Order.objects.select_related("customer").prefetch_related("lines", "events__actor"), pk=pk)
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
    "order", "created", "status", "channel", "customer", "pickup", "product", "unit", "ordered", "real_weight",
    "unit_price", "line_total", "order_total", "gst_included", "paid", "payment_method",
]


def export_rows(queryset):
    tz = timezone.get_current_timezone()
    fmt = "%Y-%m-%d %H:%M"
    for order in queryset.select_related("customer").prefetch_related("lines"):
        for line in order.lines.all():
            yield [
                order.number, timezone.localtime(order.created_at, tz).strftime(fmt), order.status, order.channel,
                order.customer.name if order.customer else "", timezone.localtime(order.pickup_at, tz).strftime(fmt) if order.pickup_at else "",
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
