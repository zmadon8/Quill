"""Clients for the Fee Register (owner round 2026-11).

A Client is the person or company a matter is for, kept as a list per profile and chosen (optionally) on each matter. Matters and their
memos can then be filtered and sorted by Client wherever they can be filtered and sorted by Partner. It is not the Client Position text
(the party role typed on a matter and copied onto its memos).

Names are 1 to 200 characters, unique per profile whatever the case. Deleting a client leaves its matters with no client.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count
from django.db.models.functions import Lower

from fees.errors import FeesError
from fees.models import Client, Matter
from fees.services import history
from fees.services.firms import validate_name
from fees.services.memos import touch

__all__ = ["MAX_CLIENT_NAME", "list_clients", "choices", "choices_for_firm", "create_client", "rename_client", "delete_client", "find_or_create", "set_matter_client"]

MAX_CLIENT_NAME = 200


def list_clients(profile):
    """Every client of the profile, by name, each with ``matter_count``."""
    return list(Client.objects.filter(profile=profile).annotate(matter_count=Count("matters")).order_by(Lower("name"), "pk"))


def choices(profile):
    """``[{"id", "name"}]`` by name, for a drop-down."""
    return [{"id": pk, "name": name} for pk, name in Client.objects.filter(profile=profile).order_by(Lower("name"), "pk").values_list("pk", "name")]


def choices_for_firm(profile, firm_id, keep_id=None):
    """``[{"id", "name"}]`` for the matter form (owner round 2026-11): only the clients of this firm's ACTIVE matters, plus ``keep_id`` (the
    matter's own client) so a saved choice is never lost. Another client is reached by typing its name in "or a new client" (an existing
    name, in any case, is reused, never copied)."""
    if firm_id is None:
        return []
    ids = set(Matter.objects.filter(profile=profile, firm_id=firm_id, is_archived=False, client__isnull=False).values_list("client_id", flat=True))
    if keep_id:
        ids.add(keep_id)
    return [{"id": pk, "name": name} for pk, name in Client.objects.filter(profile=profile, pk__in=ids).order_by(Lower("name"), "pk").values_list("pk", "name")]


def _clean(profile, name, exclude_pk=None):
    clean = validate_name(name, "INVALID_CLIENT_NAME", MAX_CLIENT_NAME)
    clash = Client.objects.filter(profile=profile, name__iexact=clean)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise FeesError("DUPLICATE_CLIENT_NAME", f'Client "{clean}" already exists')
    return clean


def _get(profile, client_id):
    client = Client.objects.filter(profile=profile, pk=client_id).first()
    if client is None:
        raise FeesError("CLIENT_NOT_FOUND", "That client was not found.")
    return client


def create_client(profile, name):
    clean = _clean(profile, name)
    with transaction.atomic():
        client = Client.objects.create(profile=profile, name=clean)
        history.record(profile, "create", "client", client.pk, f"Added client {clean}")
        touch(profile)
    return client


def rename_client(profile, client_id, name):
    client = _get(profile, client_id)
    clean = _clean(profile, name, exclude_pk=client.pk)
    with transaction.atomic():
        old = client.name
        client.name = clean
        client.save(update_fields=["name", "updated_at"])
        history.record(profile, "update", "client", client.pk, f"Renamed client {old} to {clean}")
        touch(profile)
    return client


def delete_client(profile, client_id):
    """Delete the client; its matters keep everything else and simply have no client. Returns the number of matters that had it."""
    client = _get(profile, client_id)
    with transaction.atomic():
        count = Matter.objects.filter(profile=profile, client=client).update(client=None)
        name = client.name
        client.delete()
        history.record(profile, "delete", "client", client_id, f"Removed client {name}" + (f" from {count} matter{'s' if count != 1 else ''}" if count else ""))
        touch(profile)
    return count


def find_or_create(profile, name):
    """The client named ``name`` (any case), made if it does not exist yet. Blank gives ``None``."""
    clean = (name or "").strip()
    if not clean:
        return None
    existing = Client.objects.filter(profile=profile, name__iexact=clean).first()
    return existing or create_client(profile, clean)


def resolve(profile, client_id=None, new_name=""):
    """The client a matter form chose: a typed new name wins over the drop-down; neither gives ``None``. Raises on an unknown id."""
    if (new_name or "").strip():
        return find_or_create(profile, new_name)
    if client_id in (None, ""):
        return None
    return _get(profile, client_id)


def set_matter_client(profile, matter, client):
    """Give ``matter`` its client (``None`` clears it). The caller is inside the matter save's transaction."""
    if (client.pk if client else None) == matter.client_id:
        return
    matter.client = client
    matter.save(update_fields=["client", "updated_at"])
