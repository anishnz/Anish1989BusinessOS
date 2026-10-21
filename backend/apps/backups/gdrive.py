"""
Google Drive for backup copies.

- Sign-in with OAuth 2.0 (authorization code + PKCE). The only permission
  asked for is `drive.file`: the platform can see and change only the files and
  folder it created itself, not the rest of the Drive.
- Uploads are resumable, in 8 MiB parts, and Google's MD5 of the uploaded file
  is compared with the local file.
- Only Google's fixed addresses are called. Error messages never contain
  tokens or secrets.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
FILES_URL = "https://www.googleapis.com/drive/v3/files"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
ABOUT_URL = "https://www.googleapis.com/drive/v3/about"
SCOPE = "https://www.googleapis.com/auth/drive.file"
FOLDER_TYPE = "application/vnd.google-apps.folder"
PART_SIZE = 8 * 1024 * 1024  # must be a multiple of 256 KiB
TIMEOUT = (10, 120)
RETRIES = 5
FILE_ID = re.compile(r"[A-Za-z0-9_-]{10,200}")


class DriveError(Exception):
    """A Google Drive problem in plain words."""


class DriveAccessRemoved(DriveError):
    """The Google account removed the platform's access, or the sign-in expired."""


@dataclass(frozen=True)
class Account:
    client_id: str
    client_secret: str
    refresh_token: str


def _sleep(seconds: float) -> None:  # replaced in tests
    time.sleep(seconds)


def _request(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", TIMEOUT)
    kwargs.setdefault("allow_redirects", False)
    try:
        return requests.request(method, url, **kwargs)
    except requests.Timeout as exc:
        raise DriveError("Google Drive did not answer in time.") from exc
    except requests.RequestException as exc:
        raise DriveError("Could not reach Google Drive. Check the server's internet connection.") from exc


def _fail(response: requests.Response, what: str) -> DriveError:
    code = response.status_code
    log.warning("Google Drive %s failed: HTTP %s %s", what, code, response.text[:500])
    if code in (401, 403):
        try:
            reason = response.json()["error"]["errors"][0]["reason"]
        except (ValueError, KeyError, IndexError, TypeError):
            reason = ""
        if reason in ("storageQuotaExceeded", "quotaExceeded"):
            return DriveError("The Google Drive is full. Free up space or buy more storage.")
        if reason in ("rateLimitExceeded", "userRateLimitExceeded"):
            return DriveError("Google Drive is limiting requests. It will be tried again next time.")
        return DriveAccessRemoved("Google Drive refused access. Connect Google Drive again.")
    if code == 404:
        return DriveError(f"Google Drive could not find the file or folder ({what}).")
    return DriveError(f"Google Drive answered with HTTP {code} ({what}).")


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------
def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def sign_in_url(*, client_id: str, redirect_uri: str, state: str, code_challenge: str, login_hint: str = "") -> str:
    params = {
        "client_id": client_id, "redirect_uri": redirect_uri, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": code_challenge, "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(*, client_id: str, client_secret: str, code: str, redirect_uri: str, code_verifier: str) -> dict:
    r = _request("POST", TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret, "code": code, "grant_type": "authorization_code",
        "redirect_uri": redirect_uri, "code_verifier": code_verifier,
    })
    if r.status_code != 200:
        log.warning("Google code exchange failed: HTTP %s %s", r.status_code, r.text[:300])
        if r.status_code == 401 or "invalid_client" in r.text:
            raise DriveError("Google did not accept the sign-in app (client ID or secret). Check it on the Integrations page.")
        raise DriveError("Google did not accept the sign-in. Try connecting again.")
    data = r.json()
    if not data.get("refresh_token"):
        raise DriveError("Google did not give lasting access. Try connecting again.")
    if SCOPE not in (data.get("scope") or "").split():
        raise DriveError("Google Drive access was not allowed. Connect again and tick the Google Drive permission.")
    return data


def access_token(account: Account) -> str:
    r = _request("POST", TOKEN_URL, data={
        "client_id": account.client_id, "client_secret": account.client_secret,
        "refresh_token": account.refresh_token, "grant_type": "refresh_token",
    })
    if r.status_code == 200 and r.json().get("access_token"):
        return r.json()["access_token"]
    log.warning("Google token refresh failed: HTTP %s %s", r.status_code, r.text[:300])
    if "invalid_grant" in r.text:
        raise DriveAccessRemoved("Google Drive access was removed or has expired. Connect Google Drive again.")
    if r.status_code == 401 or "invalid_client" in r.text:
        raise DriveError("Google did not accept the sign-in app (client ID or secret).")
    raise DriveError(f"Google sign-in answered with HTTP {r.status_code}.")


def revoke(refresh_token: str) -> bool:
    """Tell Google to remove the platform's access (best effort)."""
    try:
        r = _request("POST", REVOKE_URL, data={"token": refresh_token})
    except DriveError:
        return False
    return r.status_code == 200


def check_sign_in_app(client_id: str, client_secret: str) -> tuple[bool, str]:
    """
    Safe test for the sign-in app: exchange a made-up code. Google answers
    "invalid_grant" when the client ID and secret are right, and
    "invalid_client" when they are wrong. Nothing is created.
    """
    r = _request("POST", TOKEN_URL, data={
        "client_id": client_id, "client_secret": client_secret, "code": "test-" + secrets.token_hex(8),
        "grant_type": "authorization_code", "redirect_uri": "https://localhost/",
    })
    if "invalid_grant" in r.text or "redirect_uri_mismatch" in r.text:
        return True, "Google accepted the client ID and secret."
    if "invalid_client" in r.text or r.status_code == 401:
        return False, "Google did not accept the client ID or client secret."
    return False, f"Google answered with HTTP {r.status_code}."


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def account_email(token: str) -> str:
    r = _request("GET", ABOUT_URL, headers=_auth(token), params={"fields": "user(emailAddress)"})
    if r.status_code != 200:
        raise _fail(r, "account")
    return (r.json().get("user") or {}).get("emailAddress", "")


def storage(token: str) -> dict:
    """{"limit": bytes or None (unlimited), "usage": bytes}."""
    r = _request("GET", ABOUT_URL, headers=_auth(token), params={"fields": "storageQuota(limit,usage)"})
    if r.status_code != 200:
        raise _fail(r, "storage")
    quota = r.json().get("storageQuota") or {}
    return {"limit": int(quota["limit"]) if quota.get("limit") else None, "usage": int(quota.get("usage") or 0)}


# ---------------------------------------------------------------------------
# Folder and files
# ---------------------------------------------------------------------------
def _valid_id(file_id: str) -> str:
    if not FILE_ID.fullmatch(file_id or ""):
        raise DriveError("Google Drive gave an unexpected file id.")
    return file_id


def ensure_folder(token: str, folder_id: str, name: str) -> str:
    """The backup folder's id. Creates the folder again if it was deleted."""
    if folder_id:
        r = _request("GET", f"{FILES_URL}/{_valid_id(folder_id)}", headers=_auth(token), params={"fields": "id,trashed"})
        if r.status_code == 200 and not r.json().get("trashed"):
            return folder_id
        if r.status_code not in (200, 404):
            raise _fail(r, "folder")
    r = _request("POST", FILES_URL, headers=_auth(token), params={"fields": "id"}, json={"name": name, "mimeType": FOLDER_TYPE})
    if r.status_code != 200:
        raise _fail(r, "create folder")
    return _valid_id(r.json()["id"])


def md5_file(path: str) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(PART_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _uploaded_until(session_url: str, token: str, total: int) -> int | dict:
    """Ask Google how much of an interrupted upload arrived. Returns the next byte, or the file if complete."""
    r = _request("PUT", session_url, headers={**_auth(token), "Content-Range": f"bytes */{total}", "Content-Length": "0"})
    if r.status_code in (200, 201):
        return r.json()
    if r.status_code == 308:
        received = r.headers.get("Range", "")
        return int(received.rsplit("-", 1)[1]) + 1 if received else 0
    raise _fail(r, "upload status")


def upload(token: str, folder_id: str, path: str, name: str) -> dict:
    """Upload `path` into the folder. Returns {"id", "md5Checksum", "size"} and checks the MD5."""
    total = os.path.getsize(path)
    r = _request(
        "POST", UPLOAD_URL, params={"uploadType": "resumable", "fields": "id,md5Checksum,size"},
        headers={**_auth(token), "X-Upload-Content-Type": "application/octet-stream", "X-Upload-Content-Length": str(total)},
        json={"name": name, "parents": [_valid_id(folder_id)], "appProperties": {"anish1989": "backup"}},
    )
    if r.status_code != 200 or not r.headers.get("Location", "").startswith("https://www.googleapis.com/"):
        raise _fail(r, "start upload")
    session_url = r.headers["Location"]
    position, result, failures = 0, None, 0
    with open(path, "rb") as fh:
        while result is None:
            fh.seek(position)
            part = fh.read(PART_SIZE)
            end = position + len(part) - 1
            try:
                r = _request("PUT", session_url, data=part, headers={
                    **_auth(token), "Content-Length": str(len(part)), "Content-Range": f"bytes {position}-{end}/{total}",
                })
                if r.status_code in (200, 201):
                    result = r.json()
                elif r.status_code == 308:
                    received = r.headers.get("Range", "")
                    position = int(received.rsplit("-", 1)[1]) + 1 if received else 0
                elif r.status_code >= 500 or r.status_code == 429:
                    raise DriveError(f"Google Drive answered with HTTP {r.status_code} (upload).")
                else:
                    raise _fail(r, "upload")
            except DriveAccessRemoved:
                raise
            except DriveError:
                failures += 1
                if failures > RETRIES:
                    raise
                _sleep(2**failures)
                state = _uploaded_until(session_url, token, total)
                if isinstance(state, dict):
                    result = state
                else:
                    position = state
    if result.get("md5Checksum") != md5_file(path):
        delete(token, result.get("id", ""))
        raise DriveError("The copy in Google Drive did not match the backup, so it was removed. It will be tried again next time.")
    return result


def list_backups(token: str, folder_id: str, extension: str) -> list[dict]:
    """Backup files the platform created in the folder: [{"id", "name", "createdTime", "size"}]."""
    files, page = [], None
    while True:
        params = {
            "q": f"'{_valid_id(folder_id)}' in parents and trashed = false",
            "fields": "nextPageToken,files(id,name,createdTime,size,md5Checksum)", "pageSize": 1000,
        }
        if page:
            params["pageToken"] = page
        r = _request("GET", FILES_URL, headers=_auth(token), params=params)
        if r.status_code != 200:
            raise _fail(r, "list files")
        data = r.json()
        files += [f for f in data.get("files", []) if f.get("name", "").endswith(extension)]
        page = data.get("nextPageToken")
        if not page:
            return files


def delete(token: str, file_id: str) -> None:
    if not file_id:
        return
    r = _request("DELETE", f"{FILES_URL}/{_valid_id(file_id)}", headers=_auth(token))
    if r.status_code not in (200, 204, 404):
        raise _fail(r, "delete")


def download(token: str, file_id: str, dest: str) -> str:
    """Download a file to `dest`. Returns its MD5."""
    digest = hashlib.md5(usedforsecurity=False)
    try:
        with requests.get(f"{FILES_URL}/{_valid_id(file_id)}", headers=_auth(token), params={"alt": "media"},
                          stream=True, timeout=TIMEOUT) as r:
            if r.status_code != 200:
                raise _fail(r, "download")
            with open(dest, "wb") as out:
                for block in r.iter_content(PART_SIZE):
                    out.write(block)
                    digest.update(block)
    except requests.RequestException as exc:
        raise DriveError("Could not download the copy from Google Drive.") from exc
    return digest.hexdigest()
