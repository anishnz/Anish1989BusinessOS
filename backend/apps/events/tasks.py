"""Background job for enquiries (task 3.1): events.enquiry_email tells staff about a new enquiry."""
from celery import shared_task
from django_tenants.utils import schema_context


@shared_task(name="events.enquiry_email", ignore_result=True)
def staff_email_task(schema_name: str, enquiry_id: int):
    from .models import Enquiry
    from .services import send_staff_email

    with schema_context(schema_name):
        enquiry = Enquiry.objects.select_related("customer").filter(pk=enquiry_id).first()
        if enquiry is not None:
            send_staff_email(enquiry)
