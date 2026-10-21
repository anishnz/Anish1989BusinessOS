from django import template

from apps.core import deleteguard

register = template.Library()


@register.inclusion_tag("core/delete_guard.html", takes_context=True)
def delete_guard(context):
    """The sum and the 5-second wait inside a delete form (see apps/core/deleteguard.py)."""
    return {"guard": deleteguard.issue(context["request"])}
