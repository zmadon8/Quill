"""Work out each profile's usual Investments pages ahead of time, so the first visit of the day (or after the nightly price update, which
makes every kept figure out of date) reads kept results instead of replaying the whole history.

It asks the same functions the pages ask, with the arguments a page uses when nothing is selected (all portfolios and brokers, today,
the profile's Include Dividends choice and each member's own period), so the keys match and the page finds the result. One profile's
failure never stops the others, and a run stops starting new work once ``max_seconds`` have gone (the nightly job must not be held up)."""
import logging
import time
from datetime import date

logger = logging.getLogger(__name__)


def _periods(profile):
    """The 'period for returns' choices of the profile's members (always including the standard one)."""
    from accounts.models import ProfileMembership

    periods = {"all"}
    for m in ProfileMembership.objects.filter(profile=profile, suspended=False).select_related("user"):
        periods.add(getattr(m.user, "investments_period", "all") or "all")
    return sorted(periods)


def warm_profile(profile, today=None):
    """Keep the Overview, its default chart, the Holdings rows and the alerts for ``profile``. Returns the number of results kept."""
    from investments.services import alerts, chartview, core, dashboard, holdings_page, masters

    today = today or date.today()
    settings_row = core.get_settings(profile, create=False)
    kept = 0
    for period in _periods(profile):
        dashboard.load(profile, None, None, None, settings_row.include_dividends, period)
        kept += 1
    # The Overview opens on the 1 year chart.
    chartview.value_chart(profile, 365, today, index=masters.default_index_for(profile), portfolio=None, broker=None, settings_row=settings_row)
    holdings_page.load(profile, None, None, None)
    alerts.visible(profile, today)
    return kept + 3


def warm_all(max_seconds=300, today=None):
    """Warm every live Investments profile. Returns ``{"profiles", "kept", "failed", "stopped"}``."""
    from accounts.models import Profile
    from accounts.suite import KEY_INVESTMENTS

    started = time.monotonic()
    summary = {"profiles": 0, "kept": 0, "failed": 0, "stopped": False}
    for profile in Profile.objects.filter(program=KEY_INVESTMENTS, deleted_at__isnull=True).order_by("pk"):
        if time.monotonic() - started > max_seconds:
            summary["stopped"] = True
            break
        try:
            summary["kept"] += warm_profile(profile, today)
            summary["profiles"] += 1
        except Exception:  # one profile never stops the others
            summary["failed"] += 1
            logger.exception("Warming Investments profile %s failed", profile.pk)
    return summary
