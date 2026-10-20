from django.urls import path

from . import api

urlpatterns = [
    path("", api.OrderList.as_view(), name="api_orders"),
    path("export/", api.OrderExport.as_view(), name="api_orders_export"),
    path("<int:pk>/", api.OrderDetail.as_view(), name="api_order"),
    path("<int:pk>/status/", api.OrderStatus.as_view(), name="api_order_status"),
    path("<int:pk>/weights/", api.OrderWeights.as_view(), name="api_order_weights"),
    path("<int:pk>/payment/", api.OrderPayment.as_view(), name="api_order_payment"),
]
