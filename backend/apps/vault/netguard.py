"""
Protect against server-side request forgery (SSRF).

Some providers let the business type an address (for example a local Ollama
server). Without this check, someone could point it at the platform's own
internal network (database, cloud metadata service, other containers).
Private, loopback, link-local and reserved addresses are refused unless
ALLOW_PRIVATE_NETWORK_URLS is on (only for local development).
"""
import ipaddress
import socket
from urllib.parse import urlparse

from django.conf import settings


class UnsafeURL(ValueError):
    pass


def check_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL("Only http and https addresses are allowed.")
    if not parsed.hostname:
        raise UnsafeURL("The address has no host name.")
    if getattr(settings, "ALLOW_PRIVATE_NETWORK_URLS", False):
        return url
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as exc:
        raise UnsafeURL("The host name could not be found.") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            raise UnsafeURL("Addresses on private or internal networks are not allowed.")
    return url
