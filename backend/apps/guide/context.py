"""Template context: the header's "Help" link points to the chapter about the current page (task 1.17)."""
from . import services


def help_link(request) -> dict:
    try:
        return {"help_url": services.help_for(request.path)}
    except Exception:  # noqa: BLE001 - a help link must never break a page
        return {"help_url": "/guide/"}
