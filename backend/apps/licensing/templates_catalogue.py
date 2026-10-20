"""
Industry templates (which modules a new business starts with) and default
licence limits. Plans and prices arrive in Phase 2; until then every new
business gets the trial limits below, editable by the Super Admin.
"""
from django.conf import settings

from apps.rbac.catalogue import TENANT_MODULES

# Always on for every business; cannot be switched off.
CORE_MODULES = frozenset({"users", "roles", "settings", "integrations", "audit"})

OPTIONAL_MODULES = tuple(m.code for m in TENANT_MODULES if m.code not in CORE_MODULES)

_FOOD_RETAIL = {"crm", "marketing", "products", "inventory", "orders", "finance", "hr", "websites", "reports", "ai", "tickets", "referrals", "competitors"}

INDUSTRY_MODULES = {
    "butchery": _FOOD_RETAIL,
    "fast_food": _FOOD_RETAIL,
    "restaurant": _FOOD_RETAIL | {"events"},
    "retail": _FOOD_RETAIL,
    "catering": _FOOD_RETAIL | {"events"},
    "events": {"crm", "marketing", "products", "orders", "finance", "hr", "websites", "reports", "ai", "tickets", "events", "referrals", "competitors"},
    "services": {"crm", "marketing", "orders", "finance", "hr", "websites", "reports", "ai", "tickets", "events", "referrals"},
    "education_consultancy": {"crm", "marketing", "finance", "hr", "websites", "reports", "ai", "tickets", "learning", "referrals"},
    "e_learning": {"crm", "marketing", "finance", "websites", "reports", "ai", "tickets", "learning", "referrals"},
    "jobs": {"crm", "marketing", "finance", "websites", "reports", "ai", "tickets", "jobs", "learning"},
    "other": set(OPTIONAL_MODULES),
}


def modules_for_industry(industry: str) -> set[str]:
    return set(INDUSTRY_MODULES.get(industry, INDUSTRY_MODULES["other"])) & set(OPTIONAL_MODULES)


def default_limits() -> dict:
    return {
        "max_users": getattr(settings, "LICENCE_TRIAL_MAX_USERS", 10),
        "max_websites": getattr(settings, "LICENCE_TRIAL_MAX_WEBSITES", 1),
        "storage_mb": getattr(settings, "LICENCE_TRIAL_STORAGE_MB", 1024),
        "ai_credits_monthly": getattr(settings, "LICENCE_TRIAL_AI_CREDITS", 0),
        "api_calls_monthly": getattr(settings, "LICENCE_TRIAL_API_CALLS", 10000),
    }
