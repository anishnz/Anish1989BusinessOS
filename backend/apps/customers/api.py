"""
Customers API.

GET    /api/customers/                  list (filters: q, tag, consent, archived)        crm.view
POST   /api/customers/                  add                                                crm.create
GET    /api/customers/<id>/             one customer (with consent history)                crm.view
PATCH  /api/customers/<id>/             change                                             crm.edit
DELETE /api/customers/<id>/             archive                                            crm.delete
POST   /api/customers/<id>/restore/     un-archive                                         crm.edit
POST   /api/customers/<id>/anonymise/   remove personal data (privacy request)            crm.delete
POST   /api/customers/<id>/consent/     {"given": true, "channel": "all", "note": ""}      crm.edit
POST   /api/customers/import/           CSV upload (field "file", "dry_run")               crm.import
GET    /api/customers/export/           CSV download                                       crm.export
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.audit.services import audit
from apps.core import csvtools
from apps.core.apihelpers import Pages
from apps.core.apihelpers import as_bool as _true
from apps.rbac.permissions import ModulePermission

from . import services
from .models import ConsentRecord, Customer


class ConsentRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsentRecord
        fields = ["channel", "given", "source", "note", "recorded_at"]


class CustomerSerializer(serializers.ModelSerializer):
    tag_list = serializers.ListField(read_only=True)
    last_order = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id", "name", "phone", "email", "address", "notes", "tags", "tag_list", "preferred_language", "source",
            "marketing_consent", "marketing_consent_at", "is_archived", "is_anonymised", "created_at", "updated_at", "last_order",
        ]
        read_only_fields = ["marketing_consent", "marketing_consent_at", "is_archived", "is_anonymised", "created_at", "updated_at"]

    def get_last_order(self, obj):
        """The customer's last placed order, for "Order again" in the list (task 2.5); only in the list."""
        pk, number = getattr(obj, "last_order_id", None), getattr(obj, "last_order_number", None)
        return {"id": pk, "number": number} if pk else None

    def _convert(self, func, value):
        try:
            return func(value)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages[0]) from None

    def validate_phone(self, value):
        return self._convert(services.normalise_phone, value)

    def validate_email(self, value):
        return self._convert(services.clean_email, value)

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value

    def validate(self, attrs):
        if self.instance is not None and self.instance.is_anonymised:
            raise serializers.ValidationError("This customer's personal data was removed and cannot be changed.")
        phone = attrs.get("phone", getattr(self.instance, "phone", ""))
        email = attrs.get("email", getattr(self.instance, "email", ""))
        other = services.find_duplicate(phone=phone, email=email, exclude_pk=getattr(self.instance, "pk", None))
        if other is not None:
            raise serializers.ValidationError({"duplicate": f"This phone or email already belongs to customer #{other.pk} ({other.name})."})
        return attrs


class CustomerDetailSerializer(CustomerSerializer):
    consent_records = ConsentRecordSerializer(many=True, read_only=True)

    class Meta(CustomerSerializer.Meta):
        fields = CustomerSerializer.Meta.fields + ["consent_records"]


class CustomerList(generics.ListCreateAPIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    serializer_class = CustomerSerializer
    pagination_class = Pages

    def get_queryset(self):
        params = self.request.query_params
        qs = Customer.objects.filter(is_archived=bool(_true(params.get("archived"))))
        consent = _true(params.get("consent"))
        if consent is not None:
            qs = qs.filter(marketing_consent=consent)
        if params.get("tag"):
            qs = qs.filter(tags__icontains=params["tag"].strip())
        from django.db.models import OuterRef, Subquery

        from apps.orders.models import Order
        from apps.orders.services import REORDER_FROM

        last = Order.objects.filter(customer=OuterRef("pk"), status__in=REORDER_FROM).order_by("-created_at")
        qs = qs.annotate(last_order_id=Subquery(last.values("pk")[:1]), last_order_number=Subquery(last.values("number")[:1]))
        return services.search(qs, params.get("q"))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, source=Customer.Source.MANUAL)


class CustomerDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    serializer_class = CustomerDetailSerializer
    queryset = Customer.objects.all()
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        return Response(self.get_serializer(services.archive(self.get_object(), actor=request.user)).data)


class _CustomerAction(APIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"

    def respond(self, customer):
        return Response(CustomerDetailSerializer(customer).data)


class CustomerRestore(_CustomerAction):
    permission_actions = {"POST": "edit"}

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        if customer.is_anonymised:
            return Response({"detail": "This customer's personal data was removed."}, status=status.HTTP_400_BAD_REQUEST)
        return self.respond(services.restore(customer, actor=request.user))


class CustomerAnonymise(_CustomerAction):
    permission_actions = {"POST": "delete"}

    def post(self, request, pk):
        return self.respond(services.anonymise(get_object_or_404(Customer, pk=pk), actor=request.user))


class CustomerConsent(_CustomerAction):
    permission_actions = {"POST": "edit"}

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        given = _true(request.data.get("given"))
        if given is None:
            return Response({"detail": "Send given: true or false."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            services.set_marketing_consent(
                customer, given, source=ConsentRecord.Source.STAFF,
                channel=str(request.data.get("channel") or "all")[:20], note=str(request.data.get("note") or ""), actor=request.user,
            )
        except DjangoValidationError as exc:
            return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        return self.respond(customer)


class CustomerImport(APIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    permission_actions = {"POST": "import"}
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        try:
            result = services.import_customers(request.FILES.get("file"), actor=request.user, dry_run=bool(_true(request.data.get("dry_run"))))
        except DjangoValidationError as exc:
            return Response({"ok": False, "detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result.as_dict(), status=status.HTTP_200_OK if result.ok else status.HTTP_400_BAD_REQUEST)


class CustomerExport(APIView):
    permission_classes = [ModulePermission]
    permission_module = "crm"
    permission_actions = {"GET": "export"}

    def get(self, request):
        qs = Customer.objects.filter(is_archived=False, is_anonymised=False)
        audit("crm.export", actor=request.user, metadata={"rows": qs.count()})
        return csvtools.csv_response("customers.csv", services.CSV_COLUMNS, services.export_rows(qs))
