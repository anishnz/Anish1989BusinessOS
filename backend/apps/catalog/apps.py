from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    verbose_name = "Products"

    def ready(self):
        from apps.audit.tracking import track

        from .models import Category, Product

        track(Category, exclude={"updated_at"})
        track(Product, exclude={"updated_at", "stock_quantity"})  # stock changes are in the stock history
