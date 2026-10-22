"""
Background jobs for reports:
- reports.daily_summaries: every 5 minutes (Celery beat), make and send each
  business's daily owner summary once its time has passed (task 2.7).
"""
from celery import shared_task


@shared_task(name="reports.daily_summaries", ignore_result=True)
def daily_summaries():
    from apps.core.scheduled import for_each_business

    from .summary import send_if_due

    return for_each_business(send_if_due, modules=("orders", "reports"))
