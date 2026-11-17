"""Clients for the Fee Register (owner round 2026-11, made firm-owned in 2026-12).

A Client is the person or company a matter is for. Each client belongs to exactly one firm, as a Partner does: names are 1 to 200
characters, unique within the firm whatever the case, and a matter's client is always one of its own firm's clients. A client is made
by typing its name on the matter form (it is made under the matter's firm), and it is listed, renamed and removed on its firm's Clients
page. It is not the Brief on Behalf of text (the ``client_position`` field). Deleting a client leaves its matters with no client.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import Lower

from fees.errors import FeesError
from fees.models import Client, Firm, Matter
from fees.services import history
from fees.services.firms import validate_name
from fees.services.memos import touch

__all__ = [
    "MAX_CLIENT_NAME", "list_clients_for_firm", "choices_for_firm", "create_client", "rename_client", "delete_client", "find_or_create",
    "for_firm", "resolve", "set_matter_client", "rename_for_firm", "clear_for_firm",
]

MAX_CLIENT_NAME = 200


def list_clients_for_firm(profile, firm_id):
    """The clients of one firm, by name, each with ``matter_count`` (this firm's matters, archived ones included)."""
    return list(
        Client.objects.filter(profile=profile, firm_id=firm_id)
        .annotate(matter_count=Count("matters"))
        .order_by(Lower("name"), "pk")
    )


def choices_for_firm(profile, firm_id, keep_id=None):
    """``[{"id", "name"}]`` for the matter form: every client of this firm, plus ``keep_id`` (the matter's own client, which may belong to
    the firm the matter is being moved from) so a saved choice is never lost. Another client is made by typing its name in "or a new
    client" (an existing name, in any case, is reused, never copied)."""
    if firm_id is None:
        return []
    wanted = Q(firm_id=firm_id) | Q(pk=keep_id) if keep_id else Q(firm_id=firm_id)
    rows = Client.objects.filter(wanted, profile=profile)
    return [{"id": pk, "name": name} for pk, name in rows.order_by(Lower("name"), "pk").values_list("pk", "name")]


def _firm_or_raise(profile, firm_id):
    firm = Firm.objects.filter(profile=profile, pk=firm_id).first() if firm_id is not None else None
    if firm is None:
        raise FeesError("FIRM_NOT_FOUND", f"Firm {firm_id} not found")
    return firm


def _clean(profile, firm_id, name, exclude_pk=None):
    clean = validate_name(name, "INVALID_CLIENT_NAME", MAX_CLIENT_NAME)
    clash = Client.objects.filter(profile=profile, firm_id=firm_id, name__iexact=clean)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise FeesError("DUPLICATE_CLIENT_NAME", f'Client "{clean}" already exists in this firm')
    return clean


def _get(profile, client_id, firm_id=None):
    """The client; with ``firm_id`` it must belong to that firm (a client of another firm is "not found" there)."""
    rows = Client.objects.filter(profile=profile, pk=client_id)
    if firm_id is not None:
        rows = rows.filter(firm_id=firm_id)
    client = rows.first()
    if client is None:
        raise FeesError("CLIENT_NOT_FOUND", "That client was not found.")
    return client


def create_client(profile, firm_id, name):
    _firm_or_raise(profile, firm_id)
    clean = _clean(profile, firm_id, name)
    with transaction.atomic():
        client = Client.objects.create(profile=profile, firm_id=firm_id, name=clean)
        history.record(profile, "create", "client", client.pk, f"Added client {clean}")
        touch(profile)
    return client


def rename_client(profile, client_id, name, firm_id=None):
    client = _get(profile, client_id, firm_id)
    clean = _clean(profile, client.firm_id, name, exclude_pk=client.pk)
    with transaction.atomic():
        old = client.name
        client.name = clean
        client.save(update_fields=["name", "updated_at"])
        history.record(profile, "update", "client", client.pk, f"Renamed client {old} to {clean}")
        touch(profile)
    return client


def delete_client(profile, client_id, firm_id=None):
    """Delete the client; its matters keep everything else and simply have no client. Returns the number of matters that had it."""
    client = _get(profile, client_id, firm_id)
    with transaction.atomic():
        count = Matter.objects.filter(profile=profile, client=client).update(client=None)
        name = client.name
        client.delete()
        history.record(profile, "delete", "client", client_id, f"Removed client {name}" + (f" from {count} matter{'s' if count != 1 else ''}" if count else ""))
        touch(profile)
    return count


def rename_for_firm(profile, firm_id, client_id, name):
    """Rename a client of this firm (a name another client of the firm has is refused). Returns the client."""
    return rename_client(profile, client_id, name, firm_id=firm_id)


def clear_for_firm(profile, firm_id, client_id):
    """Remove a client of this firm; its matters keep everything else and simply have no client. Returns the number of matters changed."""
    return delete_client(profile, client_id, firm_id=firm_id)


def find_or_create(profile, firm_id, name):
    """The client of the firm named ``name`` (any case), made if it does not exist yet. Blank gives ``None``."""
    clean = (name or "").strip()
    if not clean:
        return None
    existing = Client.objects.filter(profile=profile, firm_id=firm_id, name__iexact=clean).first()
    return existing or create_client(profile, firm_id, clean)


def for_firm(profile, firm_id, client):
    """``client`` as a client of ``firm_id``: itself when it already belongs there, else the firm's client of the same name (any case),
    made if needed. ``None`` stays ``None``. Used when a matter moves to another firm."""
    if client is None or client.firm_id == firm_id:
        return client
    return find_or_create(profile, firm_id, client.name)


def resolve(profile, firm_id, client_id=None, new_name=""):
    """The client a matter form chose, as a client of the matter's firm ``firm_id``: a typed new name wins over the drop-down; neither
    gives ``None``. Raises on an unknown id. A listed client of another firm (the matter's old firm, when it is being moved) is
    replaced by the target firm's client of the same name."""
    if (new_name or "").strip():
        return find_or_create(profile, firm_id, new_name)
    if client_id in (None, ""):
        return None
    return for_firm(profile, firm_id, _get(profile, client_id))


def set_matter_client(profile, matter, client):
    """Give ``matter`` its client (``None`` clears it). The caller is inside the matter save's transaction."""
    if (client.pk if client else None) == matter.client_id:
        return
    matter.client = client
    matter.save(update_fields=["client", "updated_at"])
