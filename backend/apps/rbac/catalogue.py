"""
Permission catalogue: every permission that exists, as "<module>.<action>".

Roles can only use codes listed here. To add a module, add it to
TENANT_MODULES or PLATFORM_MODULES with the actions that make sense for it.
"""
from dataclasses import dataclass

# The 17 permission actions from the master specification (section 4.1).
ACTIONS = {
    "view": "View",
    "create": "Create",
    "edit": "Edit",
    "delete": "Delete or archive",
    "approve": "Approve or reject",
    "publish": "Publish",
    "export": "Export or download",
    "import": "Import",
    "assign": "Assign or delegate",
    "configure": "Configure",
    "administer": "Administer",
    "manage_permissions": "Manage permissions",
    "manage_billing": "Manage billing",
    "execute_ai": "Execute AI tools",
    "approve_ai": "Approve AI actions",
    "manage_integrations": "Manage integrations",
    "view_audit": "View audit logs",
}

CRUD = ("view", "create", "edit", "delete")


@dataclass(frozen=True)
class Module:
    code: str
    label: str
    actions: tuple


# Modules inside each business (tenant schemas).
TENANT_MODULES = (
    Module("users", "Users and departments", CRUD + ("assign", "export")),
    Module("roles", "Roles and permissions", CRUD + ("assign", "manage_permissions")),
    Module("settings", "Business settings and modules", ("view", "configure", "administer")),
    Module("integrations", "Integrations and API keys", ("view", "configure", "manage_integrations")),
    Module("audit", "Audit log and login history", ("view_audit", "export")),
    Module("crm", "CRM: contacts, leads, pipeline", CRUD + ("assign", "import", "export")),
    Module("marketing", "Marketing campaigns", CRUD + ("approve", "publish", "export")),
    Module("products", "Products and catalogue", CRUD + ("import", "export", "publish")),
    Module("inventory", "Inventory, suppliers, purchasing", CRUD + ("approve", "import", "export")),
    Module("orders", "Orders and WhatsApp ordering", CRUD + ("approve", "assign", "export", "configure")),
    Module("finance", "Invoices, payments, reconciliation", CRUD + ("approve", "export", "import", "manage_billing")),
    Module("hr", "Employees, shifts, attendance", CRUD + ("approve", "export")),
    Module("websites", "Websites and content", CRUD + ("publish",)),
    Module("reports", "Business intelligence and reports", ("view", "create", "export")),
    Module("ai", "AI agents and automation", CRUD + ("configure", "execute_ai", "approve_ai")),
    Module("tickets", "Tickets and support", CRUD + ("assign",)),
    Module("referrals", "Referrals and rewards", CRUD + ("approve", "export")),
    Module("events", "Catering and events", CRUD + ("approve", "export")),
    Module("learning", "Courses and learning", CRUD + ("publish", "export")),
    Module("jobs", "Jobs and careers", CRUD + ("publish", "export")),
    Module("competitors", "Competitor intelligence", ("view", "create", "configure", "export")),
)

# Modules of the platform itself (public schema, Super Admin side).
PLATFORM_MODULES = (
    Module("tenants", "Tenants and licences", CRUD + ("configure", "administer")),
    Module("plans", "Plans and pricing", CRUD + ("publish",)),
    Module("platform_billing", "Platform billing and reconciliation", ("view", "create", "edit", "approve", "export", "manage_billing")),
    Module("platform_users", "Platform admin users", CRUD + ("assign",)),
    Module("platform_roles", "Platform roles", CRUD + ("assign", "manage_permissions")),
    Module("platform_settings", "Platform settings and security", ("view", "configure", "administer", "manage_integrations")),
    Module("platform_audit", "Platform audit log", ("view_audit", "export")),
    Module("support", "Support tickets", CRUD + ("assign",)),
)


def _codes(modules) -> frozenset:
    return frozenset(f"{m.code}.{a}" for m in modules for a in m.actions)


TENANT_PERMISSIONS = _codes(TENANT_MODULES)
PLATFORM_PERMISSIONS = _codes(PLATFORM_MODULES)


def is_public_schema(schema_name: str) -> bool:
    return schema_name == "public"


def modules_for(schema_name: str):
    return PLATFORM_MODULES if is_public_schema(schema_name) else TENANT_MODULES


def permissions_for(schema_name: str) -> frozenset:
    return PLATFORM_PERMISSIONS if is_public_schema(schema_name) else TENANT_PERMISSIONS


def grouped_choices(schema_name: str):
    """Choices for a checkbox matrix, grouped by module."""
    return [
        (m.label, [(f"{m.code}.{a}", ACTIONS[a]) for a in m.actions])
        for m in modules_for(schema_name)
    ]


def module_of(code: str) -> str:
    return code.split(".", 1)[0]
