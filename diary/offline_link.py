"""Round 21 (D100): the saved Offline copy behind the secret link, and the limit on how often it is downloaded.

Only ``make_copy`` and ``refresh_all`` ever build the file (the Admin's button, the Admin page and the nightly job).
A visitor following the link is only ever given the file that was saved earlier.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from accounts.forms import _client_ip
from accounts.models import OfflineDownload, OfflineLink, prune_offline_downloads

from .wordexport import service

logger = logging.getLogger(__name__)

OFFLINE_WINDOW = timedelta(hours=1)
OFFLINE_PER_IP = 20
OFFLINE_PER_LINK = 100


def make_copy(link, user=None):
    """Build the whole-diary Offline copy of ``link``'s profile and save it on the link.

    Uses the number and date formats of ``user`` (the Admin who pressed the button), else of the Admin who last made
    the link or a copy; standard formats if there is none or that user is no longer active. Raises whatever the
    builder raises; the caller decides how to report it (the previous copy is kept because nothing is saved first).
    """
    who = user or link.made_by
    if who is not None and not who.is_active:
        who = None
    result = service.offline_copy(link.profile, who, include_review=True)
    link.copy_data = result.data
    link.copy_name = result.name
    link.copy_made_at = timezone.now()
    link.copy_items = result.items
    link.copy_size = result.size
    link.copy_error = ""
    fields = ["copy_data", "copy_name", "copy_made_at", "copy_items", "copy_size", "copy_error"]
    if user is not None:
        link.made_by = user
        fields.append("made_by")
    link.save(update_fields=fields)
    return link


def refresh_all():
    """Remake the saved copy of every switched-on link whose profile is not deleted. Returns (made, failed profile ids).

    One failing profile never stops the others, and its previous copy is kept.
    """
    made = 0
    failed = []
    links = OfflineLink.objects.filter(enabled=True, profile__deleted_at__isnull=True).select_related("profile", "made_by")
    for link in list(links.order_by("profile_id")):
        try:
            make_copy(link)
            made += 1
        except Exception as exc:
            logger.exception("Offline copy refresh failed for profile %s", link.profile_id)
            message = f"The nightly refresh failed ({type(exc).__name__}). The earlier copy is kept."
            OfflineLink.objects.filter(pk=link.pk).update(copy_error=message[:300])
            failed.append(link.profile_id)
    return made, failed


def download_limited(request, link):
    """True if this visitor or this link has had too many downloads in the last hour; otherwise record this one.

    Not called for HEAD requests or resumed ranges, so a retry on a poor network is never punished.
    """
    ip = _client_ip(request)
    now = timezone.now()
    prune_offline_downloads(now)
    recent = OfflineDownload.objects.filter(link=link, at__gte=now - OFFLINE_WINDOW)
    if recent.filter(ip=ip).count() >= OFFLINE_PER_IP or recent.count() >= OFFLINE_PER_LINK:
        return True
    OfflineDownload.objects.create(link=link, ip=ip, at=now)
    return False
