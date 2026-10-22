"""
Background jobs for orders (run by the worker):
- orders.send_message: send one queued WhatsApp message to a customer (task 2.3).
"""
from celery import shared_task
from django_tenants.utils import schema_context


@shared_task(name="orders.send_message", ignore_result=True)
def send_order_message(schema_name: str, message_id: int):
    from .models import OrderMessage
    from .notify import deliver

    with schema_context(schema_name):
        message = OrderMessage.objects.filter(pk=message_id, status=OrderMessage.Status.QUEUED).first()
        if message is not None:
            deliver(message)
