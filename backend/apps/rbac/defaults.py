"""
Default roles created in every schema. Admins can change their permissions
(except System Admin / Super Admin, which always have everything) and add
their own custom roles.

Customer, Supplier, Affiliate and Student roles get no back-office
permissions: they will only see their own records through the customer
portal (built later).
"""
from .catalogue import PLATFORM_PERMISSIONS, TENANT_MODULES, TENANT_PERMISSIONS


def _all(module: str, codes=TENANT_PERMISSIONS):
    return {c for c in codes if c.startswith(f"{module}.")}


def _only(module: str, *actions):
    return {f"{module}.{a}" for a in actions}


BUSINESS_MODULES = [m.code for m in TENANT_MODULES if m.code not in {"users", "roles", "settings", "integrations", "audit"}]
VIEW_EVERYTHING = {f"{m.code}.view" for m in TENANT_MODULES if "view" in m.actions}

TENANT_ROLES = {
    "system_admin": ("System Admin", "Full control of this business, its users, roles and settings.", set(TENANT_PERMISSIONS)),
    "it_admin": (
        "IT Admin",
        "Users, integrations, security settings and technical support.",
        _all("users") | _all("integrations") | _only("settings", "view", "configure") | _only("roles", "view", "assign") | _only("audit", "view_audit"),
    ),
    "business_owner": (
        "Business Owner",
        "Runs the business: all business modules, reports and the audit log.",
        set().union(*(_all(m) for m in BUSINESS_MODULES)) | _only("users", "view") | _only("roles", "view") | _only("settings", "view") | _all("audit"),
    ),
    "department_manager": (
        "Department Manager",
        "Manages a team: day-to-day records, approvals and reports.",
        _only("crm", "view", "create", "edit", "assign") | _only("orders", "view", "create", "edit", "approve", "assign")
        | _only("hr", "view", "approve") | _only("reports", "view", "export") | _only("tickets", "view", "create", "edit", "assign")
        | _only("products", "view") | _only("inventory", "view") | _only("users", "view"),
    ),
    "sales_manager": ("Sales Manager", "Sales pipeline, targets and the sales team.", _all("crm") | _only("orders", "view", "approve", "export") | _only("reports", "view", "export") | _only("products", "view")),
    "sales_rep": ("Sales Representative", "Works assigned leads, contacts and orders.", _only("crm", "view", "create", "edit") | _only("orders", "view", "create") | _only("products", "view")),
    "marketing_manager": ("Marketing Manager", "Campaigns, audiences and publishing.", _all("marketing") | _only("crm", "view", "export") | _only("reports", "view", "export") | _only("ai", "view", "execute_ai")),
    "marketing_staff": ("Marketing Staff", "Prepares campaigns and content for approval.", _only("marketing", "view", "create", "edit") | _only("ai", "view", "execute_ai")),
    "finance_manager": ("Finance Manager", "Financial records, reports and approvals.", _all("finance") | _only("reports", "view", "export") | _only("orders", "view") | _only("audit", "view_audit")),
    "accountant": ("Accountant", "Invoices, expenses and reconciliation.", _only("finance", "view", "create", "edit", "export", "import") | _only("reports", "view")),
    "hr_manager": ("HR Manager", "Employees, attendance, leave and rosters.", _all("hr") | _only("users", "view") | _only("reports", "view")),
    "hr_staff": ("HR Staff", "Day-to-day HR tasks.", _only("hr", "view", "create", "edit")),
    "inventory_manager": ("Inventory Manager", "Stock, suppliers and purchasing.", _all("inventory") | _all("products") | _only("reports", "view", "export")),
    "operations_manager": ("Operations Manager", "Orders, events, tickets and workflows.", _all("orders") | _all("events") | _all("tickets") | _only("inventory", "view") | _only("reports", "view")),
    "content_manager": ("Content Manager", "Websites, pages and publishing.", _all("websites") | _only("learning", "view", "create", "edit", "publish") | _only("jobs", "view", "create", "edit", "publish")),
    "ai_manager": ("AI Manager", "AI agents, budgets and approvals.", _all("ai") | _only("reports", "view")),
    "support_agent": ("Support Agent", "Handles assigned customer tickets.", _only("tickets", "view", "create", "edit") | _only("orders", "view") | _only("crm", "view")),
    "employee": ("Employee", "Own profile, shifts and assigned tasks.", _only("tickets", "view", "create")),
    "auditor": ("Auditor", "Read-only access to records and the audit log.", VIEW_EVERYTHING | _all("audit")),
    "teacher": ("Teacher or Trainer", "Assigned courses, learners and assessments.", _only("learning", "view", "create", "edit")),
    "customer": ("Customer", "Customer portal only (own orders and invoices).", set()),
    "supplier": ("Supplier", "Supplier portal only (own purchase orders).", set()),
    "affiliate": ("Affiliate", "Affiliate portal only (own referrals and commissions).", set()),
    "student": ("Student or Learner", "Learning portal only (own courses and progress).", set()),
}

PLATFORM_ROLES = {
    "super_admin": ("Super Admin", "Full control of the platform.", set(PLATFORM_PERMISSIONS)),
    "platform_billing_admin": (
        "Platform Billing Admin",
        "Platform subscriptions, invoices and reconciliation. No access to businesses' own accounting.",
        _all("platform_billing", PLATFORM_PERMISSIONS) | _only("tenants", "view") | _only("plans", "view"),
    ),
    "platform_security_admin": (
        "Platform Security Admin",
        "Security settings and monitoring. Cannot change financial records.",
        _only("platform_settings", "view", "configure") | _all("platform_audit", PLATFORM_PERMISSIONS) | _only("platform_users", "view") | _only("tenants", "view"),
    ),
    "platform_support_admin": (
        "Platform Support Admin",
        "Support tickets and troubleshooting.",
        _all("support", PLATFORM_PERMISSIONS) | _only("tenants", "view"),
    ),
}

# Roles that always have every permission and cannot be edited or deleted.
FULL_ACCESS_ROLES = {"system_admin", "super_admin"}


def default_roles_for(schema_name: str) -> dict:
    return PLATFORM_ROLES if schema_name == "public" else TENANT_ROLES
