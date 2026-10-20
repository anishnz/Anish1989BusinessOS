"""
Products API (for the React frontend and later the WhatsApp AI).

GET    /api/products/                    list (filters: q, category, available, archived, unit)  products.view
POST   /api/products/                    add                                                       products.create
GET    /api/products/<id>/               one product                                               products.view
PATCH  /api/products/<id>/               change                                                    products.edit
DELETE /api/products/<id>/               archive (kept for old orders)                             products.delete
POST   /api/products/<id>/restore/       un-archive                                                products.edit
GET    /api/products/categories/         list categories                                           products.view
POST   /api/products/categories/         add                                                       products.create
PATCH  /api/products/categories/<id>/    change                                                    products.edit
DELETE /api/products/categories/<id>/    remove (its products keep no category)                    products.delete
POST   /api/products/import/             CSV upload (field "file", "dry_run")                      products.import
GET    /api/products/export/             CSV download                                              products.export

The cost price is only shown to people who can edit products.
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from rest_framework import generics, serializers, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import csvtools
from apps.core.apihelpers import Pages
from apps.core.apihelpers import as_bool as _true
from apps.rbac import policy
from apps.rbac.permissions import ModulePermission

from . import services
from .models import Category, Product


class CategorySerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Category
        fields = ["id", "name", "sort_order", "is_active", "product_count"]

    def validate_name(self, value):
        value = value.strip()
        clash = Category.objects.filter(name__iexact=value)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError("A category with this name already exists.")
        return value


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True, default="")
    gst_amount = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    sold_by_weight = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            "id", "sku", "name", "category", "category_name", "description", "unit", "price", "gst_applies", "gst_amount",
            "cost_price", "min_quantity", "quantity_step", "sold_by_weight", "search_terms", "is_available", "is_archived",
            "created_at", "updated_at",
        ]
        read_only_fields = ["is_archived", "created_at", "updated_at"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get("request")
        if request is None or not policy.has_perm(request.user, "products.edit"):
            self.fields.pop("cost_price")

    def validate_sku(self, value):
        value = value.strip()
        if value:
            clash = Product.objects.filter(sku__iexact=value)
            if self.instance:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError("Another product already uses this SKU.")
        return value

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name is required.")
        return value


class CategoryList(generics.ListCreateAPIView):
    permission_classes = [ModulePermission]
    permission_module = "products"
    serializer_class = CategorySerializer

    def get_queryset(self):
        from django.db.models import Count, Q

        return Category.objects.annotate(product_count=Count("products", filter=Q(products__is_archived=False)))


class CategoryDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [ModulePermission]
    permission_module = "products"
    serializer_class = CategorySerializer
    queryset = Category.objects.all()
    http_method_names = ["get", "patch", "delete", "head", "options"]


class ProductList(generics.ListCreateAPIView):
    permission_classes = [ModulePermission]
    permission_module = "products"
    serializer_class = ProductSerializer
    pagination_class = Pages

    def get_queryset(self):
        params = self.request.query_params
        qs = Product.objects.select_related("category")
        archived = _true(params.get("archived"))
        qs = qs.filter(is_archived=bool(archived))
        available = _true(params.get("available"))
        if available is not None:
            qs = qs.filter(is_available=available)
        if params.get("category"):
            qs = qs.filter(category_id=params["category"]) if params["category"].isdigit() else qs.none()
        if params.get("unit"):
            qs = qs.filter(unit=params["unit"])
        return services.search(qs, params.get("q"))

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ProductDetail(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [ModulePermission]
    permission_module = "products"
    serializer_class = ProductSerializer
    queryset = Product.objects.select_related("category")
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def destroy(self, request, *args, **kwargs):
        product = services.archive(self.get_object(), actor=request.user)
        return Response(self.get_serializer(product).data)


class ProductRestore(APIView):
    permission_classes = [ModulePermission]
    permission_module = "products"
    permission_actions = {"POST": "edit"}

    def post(self, request, pk):
        product = services.restore(get_object_or_404(Product, pk=pk), actor=request.user)
        return Response(ProductSerializer(product, context={"request": request}).data)


class ProductImport(APIView):
    permission_classes = [ModulePermission]
    permission_module = "products"
    permission_actions = {"POST": "import"}
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        try:
            result = services.import_products(request.FILES.get("file"), actor=request.user, dry_run=bool(_true(request.data.get("dry_run"))))
        except DjangoValidationError as exc:
            return Response({"ok": False, "detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(result.as_dict(), status=status.HTTP_200_OK if result.ok else status.HTTP_400_BAD_REQUEST)


class ProductExport(APIView):
    permission_classes = [ModulePermission]
    permission_module = "products"
    permission_actions = {"GET": "export"}

    def get(self, request):
        include_cost = policy.has_perm(request.user, "products.edit")
        qs = Product.objects.filter(is_archived=bool(_true(request.query_params.get("archived"))))
        from apps.audit.services import audit

        audit("products.export", actor=request.user, metadata={"rows": qs.count(), "cost_included": include_cost})
        return csvtools.csv_response("products.csv", services.CSV_COLUMNS, services.export_rows(qs, include_cost=include_cost))
