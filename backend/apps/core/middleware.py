"""
DeleteGuardMiddleware (task 1.18, D-129): the admin's own delete pages
(one record, or "Delete selected") only delete after the safety check in
apps/core/deleteguard.py. Without it, nothing is deleted and the person is
sent back with the reason.
"""
import re

from django.contrib import messages
from django.shortcuts import redirect

from . import deleteguard

ADMIN_DELETE = re.compile(r"^/admin/[\w-]+/[\w-]+/[^/]+/delete/$")
ADMIN_LIST = re.compile(r"^/admin/[\w-]+/[\w-]+/$")


def is_guarded_delete(request) -> bool:
    if request.method != "POST" or request.POST.get("post") != "yes":
        return False
    if ADMIN_DELETE.match(request.path):
        return True
    return bool(ADMIN_LIST.match(request.path)) and request.POST.get("action") == "delete_selected"


class DeleteGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_guarded_delete(request):
            problem = deleteguard.check(request)
            if problem:
                messages.error(request, f"Not deleted: {problem}")
                return redirect(request.get_full_path())
        return self.get_response(request)
