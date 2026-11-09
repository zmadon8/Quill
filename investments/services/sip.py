"""SIP schedules (plan 6). A recurring purchase is recorded once; the nightly `create_sip_entries` step makes each month's entry from the NAV of
that day (the first NAV stored on or after the SIP date, within a week, since a holiday has none). By default each entry is pending and does
not count until confirmed (or corrected and confirmed) on the To complete page; a Settings choice makes final entries instead."""
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from investments.errors import InvestmentsError, not_found
from investments.models import SIP_FINAL, STATUS_FINAL, STATUS_PENDING_SIP, SipSchedule, Transaction
from investments.services import core, prices

NAV_WINDOW = 7


def _month_day(year, month, day):
    import calendar

    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def due_dates(schedule, today=None):
    """SIP dates from the start (or after the last one done) up to today."""
    today = today or date.today()
    end = min(today, schedule.end_date) if schedule.end_date else today
    d = schedule.start_date
    first = _month_day(d.year, d.month, schedule.day_of_month)
    if first < d:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        first = _month_day(nxt.year, nxt.month, schedule.day_of_month)
    out, cur = [], first
    while cur <= end:
        if schedule.last_done is None or cur > schedule.last_done:
            out.append(cur)
        nxt = (cur.replace(day=1) + timedelta(days=32)).replace(day=1)
        cur = _month_day(nxt.year, nxt.month, schedule.day_of_month)
    return out


@transaction.atomic
def add(profile, user, *, instrument, amount, day_of_month, portfolio, broker, start_date, folio=None, end_date=None):
    if instrument.profile_id not in (None, profile.pk) or portfolio.profile_id != profile.pk or broker.profile_id != profile.pk:
        raise not_found("investment, portfolio or broker")
    amount = Decimal(str(amount))
    if amount <= 0:
        raise InvestmentsError("BAD_NUMBER", "The SIP amount must be more than zero.")
    if not 1 <= int(day_of_month) <= 31:
        raise InvestmentsError("BAD_NUMBER", "The day of the month must be 1 to 31.")
    obj = SipSchedule.objects.create(profile=profile, instrument=instrument, amount=amount, day_of_month=int(day_of_month), portfolio=portfolio,
                                     broker=broker, folio=folio, start_date=start_date, end_date=end_date)
    core.touch(profile)
    return obj


@transaction.atomic
def set_active(profile, pk, active):
    obj = SipSchedule.objects.filter(pk=pk, profile=profile).first()
    if obj is None:
        raise not_found("SIP")
    obj.active = bool(active)
    obj.save(update_fields=["active"])
    core.touch(profile)
    return obj


def create_due_entries(today=None):
    """Make every due entry whose NAV is stored. Returns the number made. Entries without a NAV yet are tried again the next night."""
    from investments.services import history

    today = today or date.today()
    made = 0
    for s in SipSchedule.objects.filter(active=True).select_related("instrument", "profile"):
        mode_final = core.get_settings(s.profile, create=False).sip_mode == SIP_FINAL
        for day in due_dates(s, today):
            navs = prices.series_from(s.instrument, day, limit=1)
            if not navs or (navs[0][0] - day).days > NAV_WINDOW:
                break                       # wait for the NAV; later months wait too, so the order is kept
            nav_day, nav = navs[0]
            with transaction.atomic():
                units = (s.amount / nav).quantize(Decimal("0.0001"))
                t = Transaction.objects.create(
                    profile=s.profile, date=day, side="buy", status=STATUS_FINAL if mode_final else STATUS_PENDING_SIP, instrument=s.instrument,
                    portfolio=s.portfolio, broker=s.broker, folio=s.folio, units=units, price=nav, charges=0, allotment_date=nav_day,
                    reference=f"SIP {s.pk}", note="Created from the SIP schedule")
                history.record(s.profile, None, t, "create", summary=f"SIP entry for {s.instrument.name}")
                s.last_done = day
                s.save(update_fields=["last_done"])
                core.touch(s.profile)
            made += 1
    return made
