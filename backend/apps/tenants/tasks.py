"""
Background jobs for web addresses:
- tenants.check_custom_domains: every 15 minutes (Celery beat), the DNS check of
  businesses' own domains that are due (task 2.8).
"""
from celery import shared_task
from django_tenants.utils import get_public_schema_name, schema_context


@shared_task(name="tenants.check_custom_domains", ignore_result=True)
def check_custom_domains():
    from .custom_domains import check_due

    with schema_context(get_public_schema_name()):
        return check_due()
