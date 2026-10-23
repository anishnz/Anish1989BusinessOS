"""
Provider catalogue: what each provider needs, and a safe "test connection"
call for each one. Tests only read (for example "list models" or "who am I")
and never send messages or charge money.

Every outgoing request:
- has a 10-second timeout,
- does not follow redirects,
- goes only to the provider's fixed address, or (for providers where the
  business types an address) passes the private-network check in netguard.py.
Error messages never include secret values.
"""
from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass, field
from typing import Callable

import requests

from .netguard import UnsafeURL, check_url

TIMEOUT = 10
TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
GRAPH_API_VERSION = "v25.0"  # Meta Graph API; supported until July 2028
GMAIL_HOST = "smtp.gmail.com"
GMAIL_PORT = 587


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    required: bool = True
    help: str = ""
    default: str = ""
    kind: str = "text"  # "text", "email", "digits" or "graph_version"


@dataclass(frozen=True)
class Provider:
    code: str
    label: str
    category: str
    secret_fields: tuple = ()
    config_fields: tuple = ()
    test: Callable | None = None
    available: bool = True
    help: str = ""
    docs_url: str = ""
    extra: dict = field(default_factory=dict)


CATEGORIES = {
    "ai": "AI models",
    "messaging": "Messaging",
    "email": "Email",
    "sms": "SMS",
    "payments": "Payments",
    "search": "Search and maps",
    "backup": "Backups",
    "website": "Website protection",
}


class TestResult:
    def __init__(self, ok: bool, message: str):
        self.ok = ok
        self.message = message[:300]


def _http(method, url, **kwargs) -> requests.Response:
    return requests.request(method, url, timeout=TIMEOUT, allow_redirects=False, **kwargs)


def _from_status(response: requests.Response, ok_message: str) -> TestResult:
    code = response.status_code
    if 200 <= code < 300:
        return TestResult(True, ok_message)
    if code in (401, 403):
        return TestResult(False, f"The provider refused the key (HTTP {code}). Check that it is correct and active.")
    if code == 404:
        return TestResult(False, "The provider could not find this account or id (HTTP 404). Check the settings.")
    if code == 429:
        return TestResult(False, "The provider is rate-limiting this key (HTTP 429). Try again later or check your plan.")
    return TestResult(False, f"The provider answered with HTTP {code}.")


def _network_error(exc: Exception) -> TestResult:
    if isinstance(exc, requests.Timeout):
        return TestResult(False, "The provider did not answer within 10 seconds.")
    if isinstance(exc, UnsafeURL):
        return TestResult(False, str(exc))
    return TestResult(False, "Could not reach the provider. Check the address and the internet connection.")


def _safe(test):
    def wrapper(secrets: dict, config: dict) -> TestResult:
        try:
            return test(secrets, config)
        except (requests.RequestException, UnsafeURL, OSError) as exc:
            return _network_error(exc)

    return wrapper


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
@_safe
def test_openai(s, c):
    r = _http("GET", "https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {s['api_key']}"})
    return _from_status(r, "Connected to OpenAI.")


@_safe
def test_anthropic(s, c):
    r = _http("GET", "https://api.anthropic.com/v1/models", headers={"x-api-key": s["api_key"], "anthropic-version": "2023-06-01"})
    return _from_status(r, "Connected to Anthropic Claude.")


@_safe
def test_gemini(s, c):
    r = _http("GET", "https://generativelanguage.googleapis.com/v1beta/models", headers={"x-goog-api-key": s["api_key"]})
    return _from_status(r, "Connected to Google Gemini.")


@_safe
def test_ollama(s, c):
    base = check_url(c["base_url"].rstrip("/"))
    r = _http("GET", f"{base}/api/tags")
    return _from_status(r, "Connected to the local AI server.")


@_safe
def test_whatsapp(s, c):
    version = c.get("graph_api_version") or GRAPH_API_VERSION
    r = _http(
        "GET",
        f"https://graph.facebook.com/{version}/{c['phone_number_id']}",
        headers={"Authorization": f"Bearer {s['access_token']}"},
        params={"fields": "display_phone_number,verified_name"},
    )
    return _from_status(r, "Connected to WhatsApp Business.")


@_safe
def test_telegram(s, c):
    r = _http("GET", f"https://api.telegram.org/bot{s['bot_token']}/getMe")
    if r.status_code == 404:  # Telegram answers 404 for a wrong token
        return TestResult(False, "Telegram did not accept this bot token.")
    return _from_status(r, "Connected to Telegram.")


@_safe
def test_viber(s, c):
    r = _http("POST", "https://chatapi.viber.com/pa/get_account_info", headers={"X-Viber-Auth-Token": s["auth_token"]}, json={})
    if r.status_code == 200 and r.json().get("status") != 0:
        return TestResult(False, "Viber did not accept this token.")
    return _from_status(r, "Connected to Viber.")


@_safe
def test_twilio(s, c):
    r = _http("GET", f"https://api.twilio.com/2010-04-01/Accounts/{c['account_sid']}.json", auth=(c["account_sid"], s["auth_token"]))
    return _from_status(r, "Connected to Twilio.")


def _smtp_login(host: str, port: int, use_tls: bool, username: str, password: str, ok_message: str) -> TestResult:
    try:
        with smtplib.SMTP(host, port, timeout=TIMEOUT) as server:
            if use_tls:
                server.starttls(context=ssl.create_default_context())
            if username:
                server.login(username, password)
        return TestResult(True, ok_message)
    except smtplib.SMTPAuthenticationError:
        return TestResult(False, "The email server refused the username or password.")
    except (smtplib.SMTPException, OSError):
        return TestResult(False, "Could not connect to the email server. Check the host, port and TLS setting.")


def as_bool(value) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def gmail_app_password(secrets: dict) -> str:
    """Google shows app passwords in groups of 4 with spaces; the spaces are not part of it."""
    return "".join(secrets.get("app_password", "").split())


@_safe
def test_smtp(s, c):
    host, port = c["host"], int(c.get("port") or 587)
    check_url(f"https://{host}")  # same private-network rule for the mail server
    return _smtp_login(host, port, as_bool(c.get("use_tls", "true")), c.get("username", ""), s.get("password", ""), "Connected to the email server.")


@_safe
def test_gmail(s, c):
    result = _smtp_login(GMAIL_HOST, GMAIL_PORT, True, c["email"], gmail_app_password(s), "Connected to Gmail.")
    if not result.ok and "refused" in result.message:
        return TestResult(False, "Gmail refused the address or app password. Use an app password (not your normal password); 2-Step Verification must be on.")
    return result


@_safe
def test_google_places(s, c):
    r = _http(
        "POST",
        "https://places.googleapis.com/v1/places:searchText",
        headers={"X-Goog-Api-Key": s["api_key"], "X-Goog-FieldMask": "places.id"},
        json={"textQuery": "Auckland", "maxResultCount": 1},
    )
    return _from_status(r, "Connected to Google Places.")


def test_google_oauth_app(s, c):
    from apps.backups import gdrive

    try:
        ok, message = gdrive.check_sign_in_app(c["client_id"], s["client_secret"])
    except gdrive.DriveError as exc:
        return TestResult(False, str(exc))
    return TestResult(ok, message)


def test_google_drive(s, c):
    from apps.backups import gdrive

    try:
        token = gdrive.access_token(gdrive.Account(c["client_id"], s["client_secret"], s["refresh_token"]))
        email = gdrive.account_email(token)
    except gdrive.DriveError as exc:
        return TestResult(False, str(exc))
    return TestResult(True, f"Connected to Google Drive ({email}).")


def test_turnstile(s, c):
    """Ask Cloudflare to check a made-up token: a working secret key gets "invalid-input-response"."""
    try:
        response = requests.post(TURNSTILE_VERIFY_URL, data={"secret": s.get("secret_key", ""), "response": "connection-test"},
                                 timeout=TIMEOUT, allow_redirects=False)
        codes = response.json().get("error-codes", []) if response.ok else []
    except (requests.RequestException, ValueError) as exc:
        return _network_error(exc)
    if "invalid-input-secret" in codes or "missing-input-secret" in codes:
        return TestResult(False, "Cloudflare does not know this secret key. Copy it again from Turnstile in the Cloudflare dashboard.")
    if not response.ok:
        return TestResult(False, f"Cloudflare answered with an error ({response.status_code}). Try again later.")
    return TestResult(True, "The secret key works. The enquiry form now shows the Cloudflare check.")


def test_bank_transfer(s, c):
    return TestResult(True, "Bank details saved. They are shown on invoices for manual bank transfer.")


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
PROVIDERS = {
    p.code: p
    for p in [
        Provider("openai", "OpenAI", "ai", (Field("api_key", "API key"),), (Field("model", "Default model", False, default="gpt-5.4-mini", help="A small, cheap model with tools. Used by the AI assistant (task 2.4)."),), test_openai, docs_url="https://platform.openai.com/api-keys"),
        Provider("anthropic", "Anthropic Claude", "ai", (Field("api_key", "API key"),), (Field("model", "Default model", False, default="claude-haiku-5-5", help="A small, cheap model with tools. Used by the AI assistant (task 2.4)."),), test_anthropic, docs_url="https://console.anthropic.com/settings/keys"),
        Provider("gemini", "Google Gemini", "ai", (Field("api_key", "API key"),), (Field("model", "Default model", False, default="gemini-3.5-flash-lite", help="A small, cheap model with tools. Used by the AI assistant (task 2.4)."),), test_gemini, docs_url="https://aistudio.google.com/apikey"),
        Provider("ollama", "Local / open model (Ollama)", "ai", (), (Field("base_url", "Server address", help="For example https://ollama.example.com"), Field("model", "Model", False)), test_ollama, help="A model you run yourself. Must be reachable from the platform."),
        Provider(
            "whatsapp_cloud", "WhatsApp Business (Cloud API)", "messaging",
            (
                Field("access_token", "Access token", help="A permanent System User token from Meta Business Settings."),
                Field("app_secret", "App secret", help="Meta app > App settings > Basic. Used to check that incoming messages really come from Meta."),
            ),
            (
                Field("phone_number_id", "Phone number ID", kind="digits"),
                Field("business_account_id", "WhatsApp Business account ID", False, kind="digits"),
                Field("graph_api_version", "Graph API version", False, default=GRAPH_API_VERSION, kind="graph_version"),
                Field("webhook_verify_token", "Webhook verify token", False, help="Leave empty to create one. Paste it into Meta's webhook settings."),
            ),
            test_whatsapp, docs_url="https://developers.facebook.com/docs/whatsapp/cloud-api/get-started",
        ),
        Provider("viber", "Viber bot", "messaging", (Field("auth_token", "Bot auth token"),), (), test_viber),
        Provider("telegram", "Telegram bot", "messaging", (Field("bot_token", "Bot token"),), (), test_telegram, help="Create a bot with @BotFather to get a token."),
        Provider(
            "smtp", "Email (SMTP)", "email", (Field("password", "Password", False),),
            (Field("host", "Server"), Field("port", "Port", False, default="587"), Field("username", "Username", False), Field("use_tls", "Use TLS (true/false)", False, default="true"), Field("from_email", "From address", kind="email")),
            test_smtp,
        ),
        Provider(
            "gmail", "Gmail", "email",
            (Field("app_password", "App password", help="16 letters from Google Account > Security > 2-Step Verification > App passwords. Not your normal Gmail password."),),
            (Field("email", "Gmail address", kind="email"), Field("from_name", "Sender name", False, help="For example Gorkha Butchery")),
            test_gmail, docs_url="https://myaccount.google.com/apppasswords",
            help="Sends invitations, password resets and notices from a Gmail account (about 500 emails a day for a personal account).",
        ),
        Provider("twilio", "SMS (Twilio)", "sms", (Field("auth_token", "Auth token"),), (Field("account_sid", "Account SID"), Field("from_number", "Sending number")), test_twilio),
        Provider(
            "bank_transfer", "Bank transfer details", "payments", (),
            (Field("account_name", "Account name"), Field("account_number", "Account number"), Field("bank_name", "Bank", False), Field("reference_hint", "Payment reference instructions", False, default="Use your invoice number")),
            test_bank_transfer, help="Your business's own receiving account, shown on invoices.",
        ),
        Provider("stripe", "Stripe", "payments", available=False, help="Coming in a later phase."),
        Provider("windcave", "Windcave", "payments", available=False, help="Coming in a later phase."),
        Provider("paypal", "PayPal", "payments", available=False, help="Coming in a later phase."),
        Provider(
            "turnstile", "Cloudflare Turnstile (spam check on the enquiry form)", "website",
            (Field("secret_key", "Secret key"),), (Field("site_key", "Site key", help="Starts with 0x. From Turnstile in the Cloudflare dashboard."),),
            test_turnstile, docs_url="https://dash.cloudflare.com/?to=/:account/turnstile",
            help="Free. In Cloudflare, add a Turnstile widget with every web address of your website (for example "
                 "yourbusiness.anish1989.com.np and your own domain). Without it, the form uses a hidden field and limits instead.",
        ),
        Provider("google_places", "Google Places (competitor search)", "search", (Field("api_key", "API key"),), (), test_google_places),
        Provider(
            "google_oauth_app", "Google sign-in app (for Google Drive backups)", "backup",
            (Field("client_secret", "Client secret"),), (Field("client_id", "Client ID"),), test_google_oauth_app,
            docs_url="https://console.cloud.google.com/apis/credentials",
            help="An OAuth client of type 'Web application' from Google Cloud, with the Google Drive API turned on. "
                 "Businesses without their own sign-in app use the platform's. See user guide 12.6.",
        ),
        Provider(
            "google_drive", "Google Drive (backup copies)", "backup",
            (Field("refresh_token", "Google access"), Field("client_secret", "Client secret")),
            (Field("client_id", "Client ID"), Field("account_email", "Google account", False, kind="email")),
            test_google_drive, extra={"connect_page": "backups"},
            help="Connect it on the Backups page with 'Connect Google Drive'.",
        ),
    ]
}


def get(code: str) -> Provider:
    provider = PROVIDERS.get(code)
    if provider is None or not provider.available:
        raise KeyError(code)
    return provider
