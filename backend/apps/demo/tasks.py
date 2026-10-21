"""Background jobs for "Install test data" and "Remove test data" (task 1.18). Each takes a minute or two."""
from celery import shared_task
from django_tenants.utils import get_public_schema_name, schema_context


@shared_task(name="demo.install", ignore_result=True)
def install_test_data(actor_email: str = ""):
    from .services import install

    with schema_context(get_public_schema_name()):
        return install(actor_email=actor_email)


@shared_task(name="demo.remove", ignore_result=True)
def remove_test_data(actor_email: str = ""):
    from .services import remove

    with schema_context(get_public_schema_name()):
        return remove(actor_email=actor_email)
