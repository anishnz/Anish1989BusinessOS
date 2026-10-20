"""
DRF permission classes.

    class CustomerList(APIView):
        permission_classes = [ModulePermission]
        permission_module = "crm"          # GET -> crm.view, POST -> crm.create, ...

    class ApproveInvoice(APIView):
        permission_classes = [requires("finance.approve")]
"""
from rest_framework.permissions import BasePermission

from . import policy

METHOD_ACTIONS = {
    "GET": "view",
    "HEAD": "view",
    "OPTIONS": "view",
    "POST": "create",
    "PUT": "edit",
    "PATCH": "edit",
    "DELETE": "delete",
}


class ModulePermission(BasePermission):
    message = "You do not have permission to do this."

    def has_permission(self, request, view):
        module = getattr(view, "permission_module", None)
        action = getattr(view, "permission_actions", {}).get(request.method) or METHOD_ACTIONS.get(request.method)
        if not module or not action:
            return False  # deny by default when a view is not configured
        return policy.require(request.user, f"{module}.{action}", request=request._request).allowed


def requires(*codes):
    """Permission class that needs every listed permission code."""

    class _Requires(BasePermission):
        message = "You do not have permission to do this."

        def has_permission(self, request, view):
            return all(policy.require(request.user, code, request=request._request).allowed for code in codes)

    _Requires.__name__ = "Requires_" + "_".join(c.replace(".", "_") for c in codes)
    return _Requires
