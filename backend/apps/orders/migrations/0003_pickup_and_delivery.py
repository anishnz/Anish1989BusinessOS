"""
Task 2.1: pickup or delivery on every order.

- The pickup time becomes the due time (the pickup time or the start of the
  delivery window); existing times are kept (D-125).
- Delivery address, area and fee; the "Out for delivery" status.
- Roles that already had every Orders permission get the new Orders –
  Configure permission (D-124). Other roles are left as they are.
"""

import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


# Every Orders permission before task 2.1 added "configure".
OLD_ORDER_CODES = {"orders.view", "orders.create", "orders.edit", "orders.delete", "orders.approve", "orders.assign", "orders.export"}


def add_configure(apps, schema_editor):
    Role = apps.get_model("rbac", "Role")
    RolePermission = apps.get_model("rbac", "RolePermission")
    for role in Role.objects.filter(full_access=False):
        codes = set(RolePermission.objects.filter(role=role).values_list("code", flat=True))
        if OLD_ORDER_CODES <= codes and "orders.configure" not in codes:
            RolePermission.objects.create(role=role, code="orders.configure")


def remove_configure(apps, schema_editor):
    apps.get_model("rbac", "RolePermission").objects.filter(code="orders.configure").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("customers", "0002_alter_consentrecord_recorded_by_and_more"),
        ("fulfilment", "0001_initial"),
        ("orders", "0002_alter_order_created_by_alter_orderevent_actor"),
        ("rbac", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name="order",
            name="orders_orde_pickup__7f3d81_idx",
        ),
        migrations.RenameField(
            model_name="order",
            old_name="pickup_at",
            new_name="due_at",
        ),
        migrations.AddField(
            model_name="order",
            name="delivery_address",
            field=models.CharField(
                blank=True,
                help_text="Street and number, flat or unit, and delivery notes.",
                max_length=200,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="delivery_area",
            field=models.ForeignKey(
                blank=True,
                help_text="Found from the postcode or suburb when left empty.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="orders",
                to="fulfilment.deliveryarea",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="delivery_fee",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0"),
                editable=False,
                max_digits=8,
                verbose_name="Delivery fee (NZ$)",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="delivery_fee_gst",
            field=models.BooleanField(
                default=True, editable=False, verbose_name="GST in the delivery fee"
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="delivery_postcode",
            field=models.CharField(blank=True, max_length=4, verbose_name="Postcode"),
        ),
        migrations.AddField(
            model_name="order",
            name="delivery_suburb",
            field=models.CharField(blank=True, max_length=100, verbose_name="Suburb"),
        ),
        migrations.AlterField(
            model_name="order",
            name="due_at",
            field=models.DateTimeField(
                blank=True,
                help_text="The pickup time, or the start of the delivery window.",
                null=True,
                verbose_name="Pickup or delivery time",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="due_until",
            field=models.DateTimeField(
                blank=True,
                editable=False,
                help_text="The end of the chosen slot. Empty when staff typed an exact time.",
                null=True,
                verbose_name="Until",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="fulfilment",
            field=models.CharField(
                choices=[("pickup", "Pickup"), ("delivery", "Delivery")],
                default="pickup",
                max_length=10,
                verbose_name="Pickup or delivery",
            ),
        ),
        migrations.AlterField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("draft", "Draft"),
                    ("awaiting_confirmation", "Awaiting customer confirmation"),
                    ("confirmed", "Confirmed"),
                    ("preparing", "Being prepared"),
                    ("final_price_sent", "Final price sent"),
                    ("final_price_accepted", "Final price accepted"),
                    ("ready", "Ready"),
                    ("out_for_delivery", "Out for delivery"),
                    ("completed", "Completed"),
                    ("cancelled_by_customer", "Cancelled by customer"),
                    ("cancelled_by_shop", "Cancelled by shop"),
                    ("expired", "Expired"),
                ],
                default="draft",
                editable=False,
                max_length=30,
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["due_at"], name="orders_order_due_at_idx"),
        ),
        migrations.AddConstraint(
            model_name="order",
            constraint=models.CheckConstraint(
                condition=models.Q(("delivery_fee__gte", 0)),
                name="orders_delivery_fee_not_negative",
            ),
        ),
        migrations.RunPython(add_configure, remove_configure),
    ]
