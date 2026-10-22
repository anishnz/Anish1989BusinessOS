"""
Background job for the AI assistant (task 2.4):
- ai.answer: answer one customer message on WhatsApp (agent.answer).
"""
from celery import shared_task
from django_tenants.utils import schema_context

MAX_TRIES = 12  # while another answer in the same chat is running, try again every 5 seconds (1 minute)


@shared_task(name="ai.answer", ignore_result=True)
def answer_task(schema_name: str, message_id: int, tries: int = 0):
    from .agent import answer

    with schema_context(schema_name):
        result = answer(message_id)
    if result == "busy" and tries < MAX_TRIES:
        answer_task.apply_async((schema_name, message_id, tries + 1), countdown=5)
    return result
