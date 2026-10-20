"""Product and category actions: CSV import/export and archiving. All audited."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from apps.audit.services import audit
from apps.core import csvtools

from .models import Category, Product

CSV_COLUMNS = [
    "sku", "name", "category", "unit", "price", "cost_price", "gst_applies",
    "min_quantity", "quantity_step", "available", "search_terms", "description",
]
UNIT_WORDS = {
    "kg": Product.Unit.KG, "per kg": Product.Unit.KG, "kilo": Product.Unit.KG, "kilogram": Product.Unit.KG,
    "each": Product.Unit.EACH, "item": Product.Unit.EACH, "ea": Product.Unit.EACH, "": Product.Unit.EACH,
    "pack": Product.Unit.PACK, "per pack": Product.Unit.PACK, "packet": Product.Unit.PACK,
}


@dataclass
class ImportResult:
    dry_run: bool
    created: int = 0
    updated: int = 0
    errors: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {"dry_run": self.dry_run, "ok": self.ok, "created": self.created, "updated": self.updated, "errors": self.errors}


def search(queryset, q: str):
    q = (q or "").strip()
    if not q:
        return queryset
    return queryset.filter(Q(name__icontains=q) | Q(sku__iexact=q) | Q(search_terms__icontains=q))


def archive(product: Product, *, actor=None) -> Product:
    product.is_archived = True
    product.is_available = False
    product.save()
    audit("products.archive", target=product, actor=actor)
    return product


def restore(product: Product, *, actor=None) -> Product:
    product.is_archived = False
    product.save()
    audit("products.restore", target=product, actor=actor)
    return product


def _parse_row(row: dict) -> dict:
    name = row.get("name", "")
    if not name:
        raise csvtools.RowError("name is required.")
    if len(name) > 150:
        raise csvtools.RowError("name is longer than 150 characters.")
    sku = row.get("sku", "")
    if len(sku) > 40:
        raise csvtools.RowError("sku is longer than 40 characters.")
    unit_word = row.get("unit", "").lower()
    if unit_word not in UNIT_WORDS:
        raise csvtools.RowError(f"unit '{row.get('unit')}' should be kg, each or pack.")
    price = csvtools.parse_decimal(row.get("price"), label="price", required=True)
    cost = csvtools.parse_decimal(row.get("cost_price"), label="cost_price")
    min_qty = csvtools.parse_decimal(row.get("min_quantity"), label="min_quantity")
    step = csvtools.parse_decimal(row.get("quantity_step"), label="quantity_step")
    for label, value in (("price", price), ("cost_price", cost)):
        if value is not None and (value < 0 or value >= Decimal("100000000")):
            raise csvtools.RowError(f"{label} must be between 0 and 99,999,999.99.")
    for label, value in (("min_quantity", min_qty), ("quantity_step", step)):
        if value is not None and value <= 0:
            raise csvtools.RowError(f"{label} must be more than 0.")
    category = row.get("category", "")
    if len(category) > 100:
        raise csvtools.RowError("category is longer than 100 characters.")
    data = {
        "sku": sku, "name": name, "unit": UNIT_WORDS[unit_word], "price": price.quantize(Decimal("0.01")),
        "gst_applies": csvtools.parse_bool(row.get("gst_applies"), default=True),
        "is_available": csvtools.parse_bool(row.get("available"), default=True),
        "category_name": category,
    }
    if cost is not None:
        data["cost_price"] = cost.quantize(Decimal("0.01"))
    if min_qty is not None:
        data["min_quantity"] = min_qty.quantize(Decimal("0.001"))
    if step is not None:
        data["quantity_step"] = step.quantize(Decimal("0.001"))
    if "search_terms" in row:
        data["search_terms"] = row["search_terms"]
    if "description" in row:
        data["description"] = row["description"]
    return data


def _find_existing(data: dict) -> Product | None:
    if data["sku"]:
        return Product.objects.filter(sku__iexact=data["sku"]).first()
    matches = list(Product.objects.filter(name__iexact=data["name"], is_archived=False)[:2])
    return matches[0] if len(matches) == 1 else None


@transaction.atomic
def import_products(upload, *, actor=None, dry_run: bool = False) -> ImportResult:
    """
    Add or update products from a CSV file. A row updates the product with the
    same SKU (or, without a SKU, the one product with the same name); other
    rows are added. Nothing is saved if any row has an error.
    """
    rows = csvtools.read_rows(upload, required={"name", "price"}, allowed=set(CSV_COLUMNS))
    result = ImportResult(dry_run=dry_run)
    parsed, seen_skus = [], set()
    for number, row in enumerate(rows, start=2):  # row 1 is the header
        try:
            data = _parse_row(row)
            key = data["sku"].lower()
            if key and key in seen_skus:
                raise csvtools.RowError(f"sku '{data['sku']}' is used twice in the file.")
            seen_skus.add(key)
            parsed.append((number, data))
        except csvtools.RowError as exc:
            result.errors.append({"row": number, "error": str(exc)})
    if result.errors:
        return result

    categories = {c.name.lower(): c for c in Category.objects.all()}
    sid = transaction.savepoint()
    for number, data in parsed:
        category_name = data.pop("category_name")
        if category_name:
            category = categories.get(category_name.lower())
            if category is None:
                category = Category.objects.create(name=category_name)
                categories[category_name.lower()] = category
            data["category"] = category
        product = _find_existing(data)
        try:
            if product is None:
                product = Product(created_by=actor, **data)
                product.full_clean()
                product.save()
                result.created += 1
            else:
                for key, value in data.items():
                    setattr(product, key, value)
                product.full_clean()
                product.save()
                result.updated += 1
        except ValidationError as exc:
            result.errors.append({"row": number, "error": "; ".join(exc.messages)})
    if result.errors or dry_run:
        transaction.savepoint_rollback(sid)
        if result.errors:
            result.created = result.updated = 0
        return result
    transaction.savepoint_commit(sid)
    audit("products.import", actor=actor, metadata={"created": result.created, "updated": result.updated})
    return result


def _number(value: Decimal) -> str:
    """1.000 -> "1", 0.500 -> "0.5", 10.000 -> "10"."""
    return format(value.normalize(), "f")


def export_rows(queryset, *, include_cost: bool):
    for p in queryset.select_related("category"):
        yield [
            p.sku, p.name, p.category.name if p.category else "", p.unit, p.price,
            (p.cost_price if p.cost_price is not None else "") if include_cost else "",
            "yes" if p.gst_applies else "no", _number(p.min_quantity), _number(p.quantity_step),
            "yes" if p.is_available else "no", p.search_terms, p.description,
        ]
