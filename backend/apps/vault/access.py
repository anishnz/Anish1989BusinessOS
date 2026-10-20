"""
Which permission each vault action needs. Businesses use the `integrations`
module; the platform (public schema) uses `platform_settings`.

    view      list connections and their masked status
    configure create, edit settings, test, disable
    manage    add or replace secret values, delete
"""
from django.db import connection

from apps.rbac import policy


def _module() -> str:
    return "platform_settings" if connection.schema_name == "public" else "integrations"


def code_for(action: str) -> str:
    return {
        "view": f"{_module()}.view",
        "configure": f"{_module()}.configure",
        "manage": f"{_module()}.manage_integrations",
    }[action]


def allowed(request, action: str) -> bool:
    return policy.require(request.user, code_for(action), request=request).allowed
