"""
Automatic audit entries when important records are created, changed or deleted.

    from apps.audit.tracking import track
    track(Role, exclude={"updated_at"})
    track(Customer, personal={"name", "phone", "email"})

`personal` fields are never written to the audit log (it cannot be edited
or deleted, and people may ask for their data to be removed). The log only
records that such a field changed.
"""
from django.db.models.signals import post_delete, post_save, pre_save

from .services import REDACTED, SECRET_KEY_PATTERN, audit

_TRACKED: dict = {}
_PERSONAL: dict = {}
PERSONAL = "[personal data]"


def _hidden(sender, name) -> bool:
    return bool(SECRET_KEY_PATTERN.search(name)) or name in _PERSONAL.get(sender, ())


def _snapshot(instance, exclude):
    data = {}
    personal = _PERSONAL.get(type(instance), ())
    for field in instance._meta.concrete_fields:
        if field.name in exclude:
            continue
        value = getattr(instance, field.attname)
        if SECRET_KEY_PATTERN.search(field.name):
            value = REDACTED
        elif field.name in personal:
            value = PERSONAL if value not in (None, "") else value
        data[field.name] = value
    return data


def _label(sender) -> str:
    return f"{sender._meta.app_label}.{sender._meta.model_name}"


def _pre_save(sender, instance, raw=False, **kwargs):
    if raw or instance.pk is None:
        instance._audit_before = None
        return
    old = sender._default_manager.filter(pk=instance.pk).first()
    instance._audit_before = _snapshot(old, _TRACKED[sender]) if old is not None else None
    # Record that a secret or personal field changed without recording the value.
    if old is not None:
        instance._audit_secret_changes = [
            f.name for f in sender._meta.concrete_fields
            if _hidden(sender, f.name) and getattr(old, f.attname) != getattr(instance, f.attname)
        ]


def _post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    exclude = _TRACKED[sender]
    after = _snapshot(instance, exclude)
    if created:
        audit(f"{_label(sender)}.create", target=instance, changes={"after": after})
        return
    before = getattr(instance, "_audit_before", None) or {}
    diff = {
        k: {"from": before.get(k), "to": v}
        for k, v in after.items()
        if before.get(k) != v and not _hidden(sender, k)
    }
    for name in getattr(instance, "_audit_secret_changes", []):
        diff[name] = {"changed": True}
    if diff:
        audit(f"{_label(sender)}.update", target=instance, changes=diff)


def _post_delete(sender, instance, **kwargs):
    audit(f"{_label(sender)}.delete", target=instance, changes={"before": _snapshot(instance, _TRACKED[sender])})


def track(model, exclude=(), personal=()):
    _TRACKED[model] = set(exclude)
    _PERSONAL[model] = set(personal)
    uid = f"audit-{_label(model)}"
    pre_save.connect(_pre_save, sender=model, dispatch_uid=f"{uid}-pre")
    post_save.connect(_post_save, sender=model, dispatch_uid=f"{uid}-post")
    post_delete.connect(_post_delete, sender=model, dispatch_uid=f"{uid}-del")
