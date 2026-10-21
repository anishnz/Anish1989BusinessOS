"""Template context: the backups reminder and the "Set up your business" link (task 1.16)."""
from . import services


def setup(request) -> dict:
    try:
        return {
            "backups_reminder": services.backups_reminder(request),
            "show_setup_link": bool(getattr(request, "user", None) and request.user.is_authenticated and request.user.is_staff
                                    and services.on_business_site() and services.can_configure(request.user)),
        }
    except Exception:  # noqa: BLE001 - a reminder must never break a page
        return {}
