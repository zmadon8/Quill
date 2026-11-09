"""The optional daily alert email (plan 14, proposed, off by default): for each profile with "Email me alerts" on, the alerts that are new
since the previous email go to the members of that profile who have an email address. The suite's email settings are used (`mailer`)."""
import logging
from datetime import date

from investments.models import AlertState, PriceMaintenanceLog
from investments.services import alerts

logger = logging.getLogger(__name__)
SENT_PREFIX = "emailed:"


def _recipients(profile):
    from accounts.models import ProfileMembership

    return sorted({m.user.email for m in ProfileMembership.objects.filter(profile=profile, suspended=False).select_related("user")
                   if m.user.email and m.user.is_active})


def send_all(today=None):
    from accounts.models import Profile
    from accounts.suite import KEY_INVESTMENTS
    from mailer import sender
    from mailer.services import is_configured

    from investments.services import core

    today = today or date.today()
    sent = skipped = 0
    if not is_configured():
        return 0, 0
    for profile in Profile.objects.filter(program=KEY_INVESTMENTS, deleted_at__isnull=True):
        if not core.get_settings(profile, create=False).alert_email:
            continue
        try:
            new = []
            for a in alerts.visible(profile, today):
                marker = (SENT_PREFIX + a["key"])[:120]
                state = AlertState.objects.filter(profile=profile, key=marker).first()
                if state and state.dismissed_on and state.dismissed_on >= a["on"]:
                    continue
                new.append((a, marker))
            to = _recipients(profile)
            if not new or not to:
                skipped += 1
                continue
            lines = [f"{a['instrument_name']}{' (' + a['portfolio_name'] + ')' if a['portfolio_name'] else ''}: {a['label']} (price date {a['on']:%-d %b %Y})"
                     for a, _m in new]
            body = "These alerts triggered:\n\n" + "\n".join(f"  - {line}" for line in lines) + (
                "\n\nAlerts use daily closing prices. They are prompts only: the decision to sell is yours.\n")
            sender.build_message(f"{sender.site_name()}: {len(new)} investment alert{'s' if len(new) != 1 else ''}", body, to).send(fail_silently=False)
            for a, marker in new:
                AlertState.objects.update_or_create(profile=profile, key=marker, defaults={"dismissed_on": a["on"]})
            sent += 1
        except Exception as exc:  # one profile's failure never stops the others
            logger.warning("Alert email for profile %s failed: %s", profile.pk, exc)
            PriceMaintenanceLog.objects.create(kind="alertmail", ok=False, message=f"profile {profile.pk}: {exc}"[:300])
    return sent, skipped
