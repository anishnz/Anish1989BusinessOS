"""
Lets the Django admin respect our roles: a Django model permission such as
"accounts.view_user" is translated to our catalogue code "users.view".
Models not listed here stay superuser-only in the admin.
"""
from . import policy

MODEL_MODULES = {
    "accounts.user": "users",
    "accounts.loginevent": "audit",
    "audit.auditevent": "audit",
    "rbac.role": "roles",
    "rbac.userrole": "roles",
    "vault.connection": "integrations",  # "platform_settings" on the platform site
    "catalog.product": "products",
    "catalog.category": "products",
    "customers.customer": "crm",
    "customers.consentrecord": "crm",
    "orders.order": "orders",
    "orders.orderline": "orders",
    "orders.ordermessage": "orders",
    "orders.customermessagesettings": "orders",  # changes also need orders.configure (see the admin)
    "orders.orderfeedback": "orders",
    "reports.dailysummarysettings": "orders",  # changes also need orders.configure (see the admin)
    "reports.dailysummary": "reports",
    "fulfilment.fulfilmentsettings": "orders",  # changes also need orders.configure (see the admin)
    "fulfilment.openinghours": "orders",
    "fulfilment.closedday": "orders",
    "fulfilment.deliveryarea": "orders",
    "inbox.conversation": "crm",
    "ai.aisettings": "ai",  # changes also need ai.configure (see the admin)
    "ai.airun": "ai",
    "events.enquirysettings": "events",  # task 3.1: see with Catering and events – View, change with – Edit
    "events.enquiry": "events",
}

DJANGO_ACTIONS = {"view": "view", "add": "create", "change": "edit", "delete": "delete"}

# Read-only logs use view_audit instead of view.
VIEW_AUDIT_MODELS = {"accounts.loginevent", "audit.auditevent"}


def translate(perm: str) -> str | None:
    try:
        app_label, codename = perm.split(".", 1)
        django_action, model_name = codename.split("_", 1)
    except ValueError:
        return None
    key = f"{app_label}.{model_name}"
    module = MODEL_MODULES.get(key)
    if module == "integrations":
        from django.db import connection

        module = "platform_settings" if connection.schema_name == "public" else "integrations"
    action = DJANGO_ACTIONS.get(django_action)
    if not module or not action:
        return None
    if key in VIEW_AUDIT_MODELS:
        return f"{module}.view_audit" if action == "view" else None
    return f"{module}.{action}"


class RolePermissionBackend:
    def authenticate(self, request, **credentials):
        return None  # permissions only; login is handled by LockoutEmailBackend

    def has_perm(self, user_obj, perm, obj=None):
        if not user_obj.is_active or not user_obj.is_staff:
            return False
        code = translate(perm)
        return bool(code) and policy.has_perm(user_obj, code)

    def has_module_perms(self, user_obj, app_label):
        if not user_obj.is_active or not user_obj.is_staff:
            return False
        modules = {module for key, module in MODEL_MODULES.items() if key.startswith(f"{app_label}.")}
        if "integrations" in modules:
            modules.add("platform_settings")
        codes = policy.effective_permissions(user_obj)
        return any(code.split(".", 1)[0] in modules for code in codes)
