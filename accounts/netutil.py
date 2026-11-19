"""The visitor's address, as far as it can be trusted behind the hosting platform's proxy."""
from django.conf import settings


def client_ip(request, limit=64):
    """The address of the visitor.

    ``X-Forwarded-For`` is a list. A visitor can put anything in it, and each proxy adds the address it saw to the END, so the
    entries at the start cannot be trusted and the right one is counted from the end: ``TRUSTED_PROXY_HOPS`` entries in
    (1 on Render: its own proxy; 2 if a CDN sits in front as well). With no header, or one that is too short, the address
    of the connection itself is used.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    entries = [part.strip() for part in forwarded.split(",") if part.strip()]
    hops = max(1, getattr(settings, "TRUSTED_PROXY_HOPS", 1))
    ip = entries[-hops] if len(entries) >= hops else ""
    return (ip or request.META.get("REMOTE_ADDR", ""))[:limit]
