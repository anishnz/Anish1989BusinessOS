#!/usr/bin/env python3
"""
Automatic screenshots for the user guide (task 1.17).

Opens a running copy of the platform in a browser, signs in, and saves the
pages listed in docs/user-guide/screenshots.json as PNG files in
docs/user-guide/images/. Chapters show them with ![text](images/<name>.png).
Run it again after a page changes, and commit the new pictures.

Needs (on the computer that runs it, not the server):
    pip install playwright
    playwright install chromium

Use a test business with made-up data (never real customers), for example:
    set GUIDE_BASE=http://gorkha.localhost:8000
    set GUIDE_EMAIL=owner@gorkha.test
    set GUIDE_PASSWORD=...            (typed by you; never saved in a file)
    set GUIDE_TOTP_SECRET=<hex>       (the test user's authenticator secret, optional)
    python tools/guide_screenshots.py [only-this-name ...]

GUIDE_PLATFORM_BASE / _EMAIL / _PASSWORD / _TOTP_SECRET do the same for
shots with "site": "platform".
"""
from __future__ import annotations

import binascii
import hashlib
import hmac
import json
import os
import re
import struct
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "docs" / "user-guide" / "screenshots.json"
OUT = ROOT / "docs" / "user-guide" / "images"
NAME = re.compile(r"^[a-z0-9-]+$")


def totp(secret_hex: str) -> str:
    """The current 6-digit code, waiting for a fresh 30-second window so the code is not reused."""
    key = binascii.unhexlify(secret_hex.strip())
    time.sleep(31 - time.time() % 30)
    counter = int(time.time()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return str((struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000).zfill(6)


def settings_for(site: str) -> dict:
    prefix = "GUIDE_PLATFORM_" if site == "platform" else "GUIDE_"
    values = {k: os.environ.get(prefix + k.upper(), "") for k in ("base", "email", "password", "totp_secret")}
    if not (values["base"] and values["email"] and values["password"]):
        sys.exit(f"Set {prefix}BASE, {prefix}EMAIL and {prefix}PASSWORD first (see the top of this file).")
    values["base"] = values["base"].rstrip("/")
    return values


def sign_in(page, s: dict) -> None:
    page.goto(s["base"] + "/admin/login/?next=/admin/")
    page.fill("#id_username", s["email"])
    page.fill("#id_password", s["password"])
    with page.expect_navigation():
        page.click("input[type=submit]")
    if page.locator("input[name=token]").count():
        if not s["totp_secret"]:
            sys.exit("This user has two-step verification: set the TOTP secret variable too.")
        page.fill("input[name=token]", totp(s["totp_secret"]))
        with page.expect_navigation():
            page.keyboard.press("Enter")
    if "/login/" in page.url:
        sys.exit("Sign-in failed. Check the email and password.")


def run_step(page, step: dict) -> None:
    """{"click": selector}, {"check": selector} (tick a box, even when it is ticked already),
    {"fill": selector, "value": text} or {"wait_for": selector}.
    "{tomorrow}" in a value becomes tomorrow's date (YYYY-MM-DD), so time slots are not in the past."""
    import datetime

    if "click" in step:
        page.locator(step["click"]).first.click()
    elif "check" in step:
        page.locator(step["check"]).first.check()
    elif "fill" in step:
        value = str(step.get("value", "")).replace("{tomorrow}", (datetime.date.today() + datetime.timedelta(days=1)).isoformat())
        page.locator(step["fill"]).first.fill(value)
    if step.get("wait_for"):
        page.wait_for_selector(step["wait_for"], timeout=15000)
    page.wait_for_load_state("networkidle")


def main(only: list[str]) -> int:
    from playwright.sync_api import sync_playwright

    shots = json.loads(CONFIG.read_text(encoding="utf-8"))
    shots = [s for s in shots if not only or s["name"] in only]
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pages = {}
        for shot in shots:
            if not NAME.match(shot["name"]):
                print(f"Skipped {shot['name']!r}: use lower-case letters, numbers and dashes.")
                continue
            site = shot.get("site", "business")
            if site not in pages:
                ctx = browser.new_context(viewport={"width": 1280, "height": 860}, color_scheme="light", locale="en-NZ")
                pages[site] = (ctx.new_page(), settings_for(site))
                sign_in(*pages[site])
            page, s = pages[site]
            page.set_viewport_size({"width": shot.get("width", 1280), "height": shot.get("height", 860)})
            page.goto(s["base"] + shot["path"])
            page.wait_for_load_state("networkidle")
            if shot.get("wait_for"):  # pages that build themselves in the browser (the staff app)
                page.wait_for_selector(shot["wait_for"], timeout=15000)
            for step in shot.get("steps", []):  # clicks and typing before the picture, for example choosing "Delivery"
                run_step(page, step)
            for selector in shot.get("hide", []):  # personal or changing details
                page.locator(selector).evaluate_all("els => els.forEach(e => e.style.visibility = 'hidden')")
            target = OUT / f"{shot['name']}.png"
            if shot.get("selector"):
                page.locator(shot["selector"]).first.screenshot(path=str(target))
            else:
                page.screenshot(path=str(target), full_page=shot.get("full_page", False))
            print(f"Saved {target.relative_to(ROOT)}")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
