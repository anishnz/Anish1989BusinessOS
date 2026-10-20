"""Signals other apps can listen to."""
from django.dispatch import Signal

# Sent after a customer's personal data was removed. Arguments: customer.
customer_anonymised = Signal()
