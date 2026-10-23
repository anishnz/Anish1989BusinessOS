"""
Website editor API (task 2.9).

GET  /api/website/                       draft, live version, fields, switches   websites.view
PUT  /api/website/draft/                 save the draft {"content": {...}}       websites.edit
POST /api/website/publish/               make the draft live                     websites.publish
GET  /api/website/versions/              the last 20 published versions          websites.view
POST /api/website/versions/<n>/restore/  copy a version into the draft           websites.edit
POST /api/website/generate/              {"field": "hero_text", "hint": ""}      websites.edit (+ an AI key)
"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.rbac.permissions import ModulePermission

from . import ai, content
from .models import WebsiteVersion


def _error(exc: DjangoValidationError) -> Response:
    if hasattr(exc, "message_dict"):
        return Response({"detail": "Some texts need fixing.", "fields": {k: " ".join(v) for k, v in exc.message_dict.items()}},
                        status=status.HTTP_400_BAD_REQUEST)
    return Response({"detail": " ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)


def _version(v: WebsiteVersion | None) -> dict | None:
    return None if v is None else {"number": v.number, "published_at": v.published_at, "published_by": v.published_by_email, "note": v.note}


def state(request) -> dict:
    from apps.rbac import policy

    row = content.draft()
    return {
        "content": content.draft_content(), "saved_at": row.updated_at, "saved_by": row.updated_by_email,
        "live": _version(content.live()), "unpublished_changes": content.unpublished_changes(),
        "fields": [{"key": f.key, "label": f.label, "limit": f.limit, "long": f.long, "help": f.help} for f in content.TEXTS],
        "switches": [{"key": k, "label": v} for k, v in content.SWITCHES.items()],
        "can_edit": policy.has_perm(request.user, "websites.edit"), "can_publish": policy.has_perm(request.user, "websites.publish"),
    }


class _Base(APIView):
    permission_classes = [ModulePermission]
    permission_module = "websites"


class WebsiteState(_Base):
    def get(self, request):
        return Response(state(request))


class DraftSave(_Base):
    permission_actions = {"PUT": "edit"}

    def put(self, request):
        try:
            content.save_draft(request.data.get("content"), actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(state(request))


class Publish(_Base):
    permission_actions = {"POST": "publish"}

    def post(self, request):
        try:
            content.publish(actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(state(request))


class Versions(_Base):
    def get(self, request):
        return Response({"results": [_version(v) for v in WebsiteVersion.objects.order_by("-number")]})


class Restore(_Base):
    permission_actions = {"POST": "edit"}

    def post(self, request, number):
        try:
            content.restore(number, actor=request.user)
        except DjangoValidationError as exc:
            return _error(exc)
        return Response(state(request))


class Generate(_Base):
    permission_actions = {"POST": "edit"}

    def post(self, request):
        try:
            text = ai.generate(str(request.data.get("field", "")), actor=request.user, hint=str(request.data.get("hint") or ""))
        except DjangoValidationError as exc:
            return _error(exc)
        return Response({"field": request.data.get("field"), "text": text})
