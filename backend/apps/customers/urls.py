from django.urls import path

from . import api

urlpatterns = [
    path("", api.CustomerList.as_view(), name="api_customers"),
    path("<int:pk>/", api.CustomerDetail.as_view(), name="api_customer"),
    path("<int:pk>/restore/", api.CustomerRestore.as_view(), name="api_customer_restore"),
    path("<int:pk>/anonymise/", api.CustomerAnonymise.as_view(), name="api_customer_anonymise"),
    path("<int:pk>/consent/", api.CustomerConsent.as_view(), name="api_customer_consent"),
    path("import/", api.CustomerImport.as_view(), name="api_customers_import"),
    path("export/", api.CustomerExport.as_view(), name="api_customers_export"),
]
