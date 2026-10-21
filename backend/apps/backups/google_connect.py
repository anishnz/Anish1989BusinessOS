"""
"Connect Google Drive" (OAuth 2.0 with PKCE).

Google only sends people back to addresses registered in Google Cloud, and
there are many business addresses, so there is one return address on the
platform's main address: /oauth/google/callback/.

1. Backups page, POST "Connect Google Drive" (password again): a random nonce
   and a PKCE verifier are kept on the server for 15 minutes, and the nonce is
   also kept in the person's session. The person goes to Google with a signed
   `state`.
2. Google -> platform /oauth/google/callback/: the signed state is checked,
   the waiting sign-in is taken (once only), the code is exchanged for lasting
   access, the result is kept encrypted for 10 minutes, and the person goes
   back to their own site. The address to go back to comes from the server,
   never from the link.
3. Own site /backups/google/finish/: only the same person, in the same browser
   session, on the same site can finish. The access goes into the vault.

Which Google sign-in app is used: the business's own (Integrations page,
"Google sign-in app"), otherwise the platform's.
"""
from __future__ import annotations

import base64
import json
import secrets
from urllib.parse import quote

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context

from apps.audit.services import audit
from apps.vault import crypto
from apps.vault.models import Connection

from . import gdrive

STATE_SALT = "backups.google.state"
FLOW_TTL = 15 * 60
DONE_TTL = 10 * 60
SESSION_KEY = "backups_google_nonce"
CALLBACK_PATH = "/oauth/google/callback/"


def _flow_key(nonce: str) -> str:
    return f"backups:google:flow:{nonce}"


def _done_key(nonce: str) -> str:
    return f"backups:google:done:{nonce}"


def _public():
    # Cache keys include the schema; both halves of the sign-in must use the same one.
    return schema_context(get_public_schema_name())


def platform_host() -> str:
    from apps.tenants.models import Tenant

    with _public():
        tenant = Tenant.objects.filter(schema_name=get_public_schema_name()).first()
        domain = tenant.get_primary_domain() if tenant else None
    return domain.domain if domain else settings.PLATFORM_DOMAIN


def redirect_uri(request=None) -> str:
    """The address to register in Google Cloud as an "Authorised redirect URI"."""
    from apps.tenants.domains import site_url

    return site_url(platform_host(), request, CALLBACK_PATH)


def _own_app() -> tuple[str, str] | None:
    from apps.vault.services import read_secrets

    conn = Connection.objects.filter(provider="google_oauth_app").exclude(status=Connection.Status.DISABLED).order_by("id").first()
    if conn is None:
        return None
    client_secret = read_secrets(conn).get("client_secret", "")
    client_id = conn.config.get("client_id", "")
    return (client_id, client_secret) if client_id and client_secret else None


def sign_in_app() -> tuple[str, str] | None:
    """(client id, client secret) of the business's own sign-in app, or the platform's."""
    app = _own_app()
    if app is None and connection.schema_name != get_public_schema_name():
        with _public():
            app = _own_app()
    return app


def start(request) -> str:
    """Begin connecting. Returns Google's sign-in address."""
    from apps.tenants.domains import main_address

    app = sign_in_app()
    if app is None:
        raise ValidationError(
            "Google Drive cannot be connected yet: the platform's Google sign-in app is not set up. "
            "The platform Super Admin adds it on the platform's Integrations page (user guide 12.6)."
        )
    tenant = getattr(connection, "tenant", None)
    return_host = main_address(tenant) if tenant is not None and main_address(tenant) else request.get_host().split(":")[0]
    nonce = secrets.token_urlsafe(24)
    verifier, challenge = gdrive.new_pkce()
    flow = {"schema": connection.schema_name, "user_id": request.user.pk, "verifier": verifier,
            "redirect_uri": redirect_uri(request), "return_host": return_host}
    with _public():
        cache.set(_flow_key(nonce), flow, FLOW_TTL)
    request.session[SESSION_KEY] = nonce
    audit("backup.drive_connect_started", actor=request.user, target_type="backups.settings", target_id="1")
    state = signing.dumps(nonce, salt=STATE_SALT)
    return gdrive.sign_in_url(client_id=app[0], redirect_uri=flow["redirect_uri"], state=state, code_challenge=challenge,
                              login_hint=getattr(request.user, "email", ""))


def _nonce_from(state: str) -> str | None:
    try:
        return signing.loads(state or "", salt=STATE_SALT, max_age=FLOW_TTL)
    except signing.BadSignature:
        return None


def _seal(nonce: str, data: dict) -> dict:
    sealed = crypto.seal(json.dumps(data).encode(), f"backups-google:{nonce}".encode())
    return {"kid": sealed.kid, **{k: base64.b64encode(getattr(sealed, k)).decode() for k in ("wrapped_key", "key_nonce", "nonce", "ciphertext")}}


def _unseal(nonce: str, box: dict) -> dict:
    sealed = crypto.Sealed(box["kid"], *(base64.b64decode(box[k]) for k in ("wrapped_key", "key_nonce", "nonce", "ciphertext")))
    return json.loads(crypto.open_sealed(sealed, f"backups-google:{nonce}".encode()))


def callback(request) -> tuple[str | None, str]:
    """
    Google's return to the platform. Returns (address to send the person to,
    problem). With a problem and no address, show the problem on this page.
    """
    from apps.tenants.domains import site_url

    state = request.GET.get("state", "")
    nonce = _nonce_from(state)
    if nonce is None:
        return None, "This sign-in link is not valid or has expired. Start again from the Backups page."
    with _public():
        flow = cache.get(_flow_key(nonce))
        cache.delete(_flow_key(nonce))
    if not flow:
        return None, "This sign-in was already used or has expired. Start again from the Backups page."
    back = site_url(flow["return_host"], request, "/backups/")
    if request.GET.get("error") or not request.GET.get("code"):
        return f"{back}?google=cancelled", ""
    result: dict = {"schema": flow["schema"], "user_id": flow["user_id"]}
    with schema_context(flow["schema"]):
        app = sign_in_app()
        try:
            if app is None:
                raise gdrive.DriveError("The Google sign-in app was removed while you were signing in.")
            tokens = gdrive.exchange_code(client_id=app[0], client_secret=app[1], code=request.GET["code"],
                                          redirect_uri=flow["redirect_uri"], code_verifier=flow["verifier"])
            email = gdrive.account_email(tokens["access_token"])
            result["box"] = _seal(nonce, {"client_id": app[0], "client_secret": app[1],
                                          "refresh_token": tokens["refresh_token"], "email": email})
        except gdrive.DriveError as exc:
            result["error"] = str(exc)
    with _public():
        cache.set(_done_key(nonce), result, DONE_TTL)
    return site_url(flow["return_host"], request, f"/backups/google/finish/?state={quote(state)}"), ""


def finish(request):
    """Save the access on the person's own site. Returns the new connection; raises ValidationError on any problem."""
    from . import services

    nonce = _nonce_from(request.GET.get("state", ""))
    expected = request.session.pop(SESSION_KEY, None)
    if nonce is None or not expected or not secrets.compare_digest(str(expected), str(nonce)):
        raise ValidationError("This sign-in did not start in this browser. Click “Connect Google Drive” again.")
    with _public():
        done = cache.get(_done_key(nonce))
        cache.delete(_done_key(nonce))
    if not done or done.get("schema") != connection.schema_name or done.get("user_id") != request.user.pk:
        raise ValidationError("This sign-in has expired or belongs to someone else. Click “Connect Google Drive” again.")
    if done.get("error"):
        raise ValidationError(done["error"])
    data = _unseal(nonce, done["box"])
    return services.save_drive_connection(client_id=data["client_id"], client_secret=data["client_secret"],
                                          refresh_token=data["refresh_token"], email=data["email"], actor=request.user)
