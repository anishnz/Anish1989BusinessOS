"""
Background jobs for orders (run by the worker):
- orders.send_message: send one queued WhatsApp message to a customer (task 2.3).
- orders.ask_feedback: every 10 minutes (Celery beat), ask for star feedback one
  hour after orders were completed, in every business (task 2.7).
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


@shared_task(name="orders.ask_feedback", ignore_result=True)
def ask_feedback():
    from apps.core.scheduled import for_each_business

    from .feedback import ask_due

    return for_each_business(ask_due, modules=("orders",))
