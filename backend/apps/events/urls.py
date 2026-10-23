from django.urls import path

from . import api, views

api_urlpatterns = [
    path("enquiries/", api.EnquiryList.as_view(), name="api_enquiries"),
    path("enquiries/from-chat/", api.FromChat.as_view(), name="api_enquiry_from_chat"),
    path("enquiries/<int:pk>/", api.EnquiryDetail.as_view(), name="api_enquiry"),
    path("enquiries/<int:pk>/status/", api.EnquiryStatus.as_view(), name="api_enquiry_status"),
    path("enquiries/<int:pk>/notes/", api.EnquiryNote.as_view(), name="api_enquiry_notes"),
]

# The public enquiry form on the business's website address
page_urlpatterns = [
    path("enquiry/", views.enquiry_form, name="enquiry_form"),
    path("enquiry/thanks/", views.enquiry_thanks, name="enquiry_thanks"),
]
