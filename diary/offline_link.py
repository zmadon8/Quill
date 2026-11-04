"""Round 21 (D100): the saved Offline copy behind the secret link, and the limit on how often it is downloaded.

Only ``make_copy`` and ``refresh_all`` ever build the file (the Admin's button, the Admin page and the nightly job).
A visitor following the link is only ever given the file that was saved earlier.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from accounts.models import OfflineDownload, OfflineLink, prune_offline_downloads

from .wordexport import service

logger = logging.getLogger(__name__)

OFFLINE_WINDOW = timedelta(hours=1)
OFFLINE_PER_IP = 20
OFFLINE_PER_LINK = 100
# Resumed downloads (a Range starting above 0) are counted too, against a looser separate cap, so a phone on a weak
# signal can resume many times but the header cannot be used to get the file without limit.
OFFLINE_RESUMES_PER_IP = 60
OFFLINE_RESUMES_PER_LINK = 300
RESUME_PREFIX = "r:"


def download_ip(request):
    """The visitor's address for the limit: the LAST X-Forwarded-For entry (added by Render's proxy, so the client
    cannot forge it), else REMOTE_ADDR. The first entry is supplied by the client and is never trusted here."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    ip = forwarded.split(",")[-1].strip() if forwarded else ""
    return (ip or request.META.get("REMOTE_ADDR", ""))[:60]


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
    links = OfflineLink.objects.filter(enabled=True, profile__deleted_at__isnull=True).select_related("profile", "made_by").defer("copy_data")
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


def download_limited(request, link, resume=False):
    """True if this visitor or this link has had too many downloads in the last hour; otherwise record this one.

    A full download (or a retry from byte 0) uses one of the 20 hourly slots per visitor and 100 per link. A resumed
    range uses the looser separate cap (60 and 300). HEAD requests carry no body and are not passed here.
    """
    ip = download_ip(request)
    now = timezone.now()
    prune_offline_downloads(now)
    recent = OfflineDownload.objects.filter(link=link, at__gte=now - OFFLINE_WINDOW)
    if resume:
        recent = recent.filter(ip__startswith=RESUME_PREFIX)
        per_ip, per_link, stored = OFFLINE_RESUMES_PER_IP, OFFLINE_RESUMES_PER_LINK, RESUME_PREFIX + ip
    else:
        recent = recent.exclude(ip__startswith=RESUME_PREFIX)
        per_ip, per_link, stored = OFFLINE_PER_IP, OFFLINE_PER_LINK, ip
    if recent.filter(ip=stored).count() >= per_ip or recent.count() >= per_link:
        return True
    OfflineDownload.objects.create(link=link, ip=stored, at=now)
    return False
