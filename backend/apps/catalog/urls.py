from django.urls import path

from . import api

urlpatterns = [
    path("", api.ProductList.as_view(), name="api_products"),
    path("<int:pk>/", api.ProductDetail.as_view(), name="api_product"),
    path("<int:pk>/restore/", api.ProductRestore.as_view(), name="api_product_restore"),
    path("<int:pk>/stock/", api.ProductStock.as_view(), name="api_product_stock"),
    path("categories/", api.CategoryList.as_view(), name="api_categories"),
    path("categories/<int:pk>/", api.CategoryDetail.as_view(), name="api_category"),
    path("import/", api.ProductImport.as_view(), name="api_products_import"),
    path("export/", api.ProductExport.as_view(), name="api_products_export"),
]
