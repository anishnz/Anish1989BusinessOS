"""Enforce the active-user limit whenever a user is created or reactivated."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django_tenants.utils import get_public_schema_name

from . import services


@receiver(pre_save, sender=get_user_model(), dispatch_uid="licensing-user-limit")
def enforce_user_limit(sender, instance, raw=False, **kwargs):
    if raw or connection.schema_name == get_public_schema_name() or not instance.is_active:
        return
    if instance.pk is not None:
        was_active = sender._default_manager.filter(pk=instance.pk, is_active=True).exists()
        if was_active:
            return  # an existing active user being edited does not count again
    services.check_can_add_active_user()
