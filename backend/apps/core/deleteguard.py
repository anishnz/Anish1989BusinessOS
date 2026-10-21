"""
Safer deleting (task 1.18, D-129).

Every delete in the admin pages needs, on top of the confirmation page:
1. the answer to a small sum (for example 4 + 7), and
2. a wait of 5 seconds before the Delete button works, then a last
   "Are you sure?" in the browser.

The server checks the answer and the wait (the browser only helps), and each
sum can be used once. Used by DeleteGuardMiddleware for the admin's delete
pages and by views with their own Remove buttons (require()).
"""
from __future__ import annotations

import secrets
import time

from django.shortcuts import render

SESSION_KEY = "delete_guard"
WAIT_SECONDS = 5
VALID_SECONDS = 15 * 60
MAX_OPEN = 20


def issue(request) -> dict:
    """A new sum for one delete page, remembered in the person's session."""
    a, b = secrets.randbelow(8) + 2, secrets.randbelow(8) + 2
    token = secrets.token_urlsafe(12)
    now = time.time()
    store = {k: v for k, v in request.session.get(SESSION_KEY, {}).items() if now - v["at"] < VALID_SECONDS}
    while len(store) >= MAX_OPEN:
        store.pop(min(store, key=lambda k: store[k]["at"]))
    store[token] = {"answer": a + b, "at": now}
    request.session[SESSION_KEY] = store
    return {"token": token, "question": f"{a} + {b}", "wait": WAIT_SECONDS}


def check(request) -> str:
    """'' when the delete may go ahead, otherwise why not. The sum is used up either way."""
    token = str(request.POST.get("guard_token", ""))
    answer = str(request.POST.get("guard_answer", "")).strip()
    store = dict(request.session.get(SESSION_KEY, {}))
    item = store.pop(token, None) if token else None
    request.session[SESSION_KEY] = store
    if item is None:
        return "Answer the sum on the delete page first."
    age = time.time() - item["at"]
    if age > VALID_SECONDS:
        return "The delete page was open too long. Answer the new sum."
    if age < WAIT_SECONDS:
        return f"Too fast: wait {WAIT_SECONDS} seconds before deleting."
    if answer != str(item["answer"]):
        return "The answer to the sum is not correct."
    return ""


def require(request, *, title: str, message: str, fields: dict, back: str):
    """
    For a view with its own Remove button: None when the person answered the
    sum (go ahead), otherwise the confirmation page to show (with the reason
    when they tried and failed).
    """
    problem = check(request) if "guard_token" in request.POST else ""
    if "guard_token" in request.POST and not problem:
        return None
    from django.contrib import admin

    return render(request, "core/confirm_delete.html", {
        **admin.site.each_context(request), "title": title, "message": message, "fields": fields, "back": back,
        "problem": problem, "guard": issue(request),
    }, status=400 if problem else 200)
