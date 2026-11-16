"""The report emails (owner round 2026-11): weekly, monthly, quarterly and annual, per Investments profile, to chosen users of that profile.

Each ticked cadence sends once its period has ended: the week Monday to Sunday, the calendar month, the calendar quarter, the financial year
1 April to 31 March. Every recipient gets an email of their own ("Dear <their name>") with the period's growth against the Default Index, the
market value of the whole profile and of each portfolio, the purchases, sales, short and long term capital gains and interest income of the
period, the same figures for the financial year so far (left out of the annual email, whose period is the year), and an Excel workbook of the holdings on the last day of the period and every transaction up to it. The annual email also carries
the Annual Report workbook for the year.

The figures come from ``annual.build_span``, the code behind the Annual Report, so they match it. The suite's email settings are used
(``mailer``). One profile's failure never stops the others; the outcome is kept on the profile's ``PeriodicEmail`` row and shown on its page.
"""
import logging
from datetime import date, timedelta

from django.utils import timezone

from investments.models import (
    CADENCE_ANNUAL, CADENCE_MONTHLY, CADENCE_QUARTERLY, CADENCE_WEEKLY, CADENCES, PeriodicEmail, PeriodicEmailRecipient, PriceMaintenanceLog,
)

logger = logging.getLogger(__name__)
XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
CADENCE_LABELS = dict(CADENCES)
LOG_KIND = "reportmail"


# ------------------------------------------------------------------ periods

def latest_period(cadence, today):
    """``(start, end)`` of the latest period of ``cadence`` that has fully ended before ``today``."""
    if cadence == CADENCE_WEEKLY:
        end = today - timedelta(days=today.weekday() + 1)          # the Sunday before this week
        return end - timedelta(days=6), end
    if cadence == CADENCE_MONTHLY:
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if cadence == CADENCE_QUARTERLY:
        first_month = ((today.month - 1) // 3) * 3 + 1
        end = date(today.year, first_month, 1) - timedelta(days=1)
        return date(end.year, ((end.month - 1) // 3) * 3 + 1, 1), end
    if cadence == CADENCE_ANNUAL:
        end = date(today.year if today.month >= 4 else today.year - 1, 3, 31)
        return date(end.year - 1, 4, 1), end
    raise ValueError(cadence)


def financial_year_label(end):
    """``"2025-26"`` for a financial year ending 31 March 2026."""
    return f"{end.year - 1}-{str(end.year)[2:]}"


def due(row, today):
    """``[(cadence, start, end)]`` for each ticked cadence whose latest ended period has not been sent yet, in page order."""
    out = []
    for cadence, _label in CADENCES:
        if not row.on(cadence):
            continue
        start, end = latest_period(cadence, today)
        last = row.last_end(cadence)
        if last is None or last < end:
            out.append((cadence, start, end))
    return out


def start_from_now(row, cadence, today):
    """A cadence just ticked starts with the NEXT period to end (the period that has already ended can be sent with "Send now")."""
    setattr(row, f"{cadence}_last_end", latest_period(cadence, today)[1])


# ------------------------------------------------------------------ who gets it

def eligible_users(profile):
    """The people who may be chosen: active, not deleted, with an unsuspended membership of the profile. Sorted by name."""
    from accounts.models import ProfileMembership

    users = {m.user for m in ProfileMembership.objects.filter(profile=profile, suspended=False).select_related("user")
             if m.user.is_active and m.user.deleted_at is None}
    return sorted(users, key=lambda u: (recipient_name(u).lower(), u.pk))


def recipient_name(user):
    """The name in "Dear ...": the user's full name, else their user name."""
    return (user.get_full_name() or "").strip() or user.username


def recipients(profile):
    """``(sendable users, problems)``: the chosen users who still have access and an email address, and a note for each one skipped."""
    allowed = {u.pk for u in eligible_users(profile)}
    ok, problems = [], []
    for r in PeriodicEmailRecipient.objects.filter(profile=profile).select_related("user").order_by("user__username"):
        name = recipient_name(r.user)
        if r.user.pk not in allowed:
            problems.append(f"{name} no longer has access to this profile")
        elif not r.user.email:
            problems.append(f"{name} has no email address")
        else:
            ok.append(r.user)
    return ok, problems


# ------------------------------------------------------------------ what it says

def rupees(value):
    """``Rs. 24,12,600.50``: the full amount with Indian grouping (never the short Thousand / Lac / Crore form)."""
    from investments.money_auto import FULL, format_amount

    return "Rs. " + format_amount(value, currency="INR", mode=FULL, symbol="")


def _pct(fraction):
    return f"{abs(fraction) * 100:.2f}%"


def _moved(fraction):
    """"grew by 2.14%", "fell by 0.80%", or "(not available)" when there is no figure."""
    if fraction is None:
        return "(not available)"
    return ("grew by " if fraction >= 0 else "fell by ") + _pct(fraction)


def _day(d):
    return f"{d.day} {d:%b %Y}"


def financial_year_start(day):
    """1 April of the financial year ``day`` falls in."""
    return date(day.year if day.month >= 4 else day.year - 1, 4, 1)


def build_report(profile, cadence, start, end):
    """The ``annual.Report`` for the period (the annual cadence is the financial year itself)."""
    from investments.services import annual, core

    settings_row = core.get_settings(profile, create=False)
    if cadence == CADENCE_ANNUAL:
        label = financial_year_label(end)
        return annual.build(profile, label, today=end + timedelta(days=1))
    fy = financial_year_label(date(end.year + (1 if end.month >= 4 else 0), 3, 31))
    return annual.build_span(profile, start, end, end, True, label=f"{start.isoformat()} to {end.isoformat()}", cutoff=annual.cutoff_for(settings_row, fy),
                             settings_row=settings_row)


def build_year_to_date(profile, cadence, start, end):
    """The ``annual.Report`` for the financial year so far (1 April to the end of the period), or None for the annual email (its period IS
    the year) and for a period that starts on 1 April (the year so far is the period itself)."""
    from investments.services import annual, core

    fy_start = financial_year_start(end)
    if cadence == CADENCE_ANNUAL or start == fy_start:
        return None
    settings_row = core.get_settings(profile, create=False)
    label = financial_year_label(date(fy_start.year + 1, 3, 31))
    return annual.build_span(profile, fy_start, end, end, True, label=label, cutoff=annual.cutoff_for(settings_row, label),
                             settings_row=settings_row, with_portfolios=False)


def _growth_line(opening, report, index):
    return (f"{opening}, your investments {_moved(report.period_return())}, whereas {index} "
            f"{_moved(report.index_return) if report.index_name else '(not available: no Default Index is set)'}.")


def _money_line(opening, report):
    return (f"{opening} you bought investments for {rupees(report.invested)} and sold investments for {rupees(report.sold)}. "
            f"Short-term capital gains: {rupees(report.short_gain)}; long-term capital gains: {rupees(report.long_gain)}; "
            f"interest income: {rupees(report.interest_income)}.")


def body(name, report, cadence, site, year=None):
    """The text of one email (the owner's wording). ``year`` is the financial year so far (``build_year_to_date``), shown beside each figure
    of the period; for a period that starts on 1 April the email says the period figures are also the year's."""
    index = f"the Index ({report.index_name})" if report.index_name else "the Index"
    fy_start = financial_year_start(report.closing)
    fy_label = financial_year_label(date(fy_start.year + 1, 3, 31))
    year_so_far = f"During the financial year {fy_label} so far ({_day(fy_start)} to {_day(report.closing)})"
    lines = [f"Dear {name},", "", _growth_line(f"During the period {_day(report.start)} to {_day(report.closing)}", report, index)]
    if year is not None:
        lines.append(_growth_line(year_so_far, year, index))
    lines.append("")
    portfolios = report.by_portfolio
    if portfolios:
        lines.append(f"The total market value of your investments is {rupees(report.closing_value)}, and that of the individual portfolios is as follows:")
        for number, (pf_name, sub) in enumerate(portfolios, start=1):
            lines.append(f"{number}. {pf_name}: {rupees(sub.closing_value)}{'.' if number == len(portfolios) else ';'}")
    else:
        lines.append(f"The total market value of your investments is {rupees(report.closing_value)}.")
    lines += ["", _money_line("During this period", report)]
    if year is not None:
        lines.append(_money_line(year_so_far + ",", year))
    elif cadence != CADENCE_ANNUAL:
        lines.append(f"This period is the start of the financial year {fy_label}, so these are also the figures for the year so far.")
    lines += ["", "Attached to this email is an excel sheet containing your holdings as on date, and a list of your transactions."]
    if cadence == CADENCE_ANNUAL:
        lines.append(f"Also attached is the Annual Report for the financial year {report.label}, as an excel sheet.")
    if report.provisional or report.approximate or (year is not None and (year.provisional or year.approximate)):
        lines += ["", "Some figures are provisional (purchases awaiting allotment are valued at cost, or a price is the nearest one available)."]
    lines += ["", "Regards,", site]
    return "\n".join(lines) + "\n"


def attachments(profile, cadence, report):
    """``[(file name, bytes, content type)]``: the Holdings and Transactions workbook, and on the annual email the Annual Report."""
    from accounts.profiles import effective_export_name, safe_file_name
    from investments import exports

    stem = effective_export_name(profile)
    files = [(safe_file_name(f"{stem} Holdings and Transactions {report.closing.isoformat()}.xlsx"),
              exports.workbook_bytes(exports.holdings_transactions_sheets(profile, as_of=report.closing, held_only=True)), XLSX_TYPE)]
    if cadence == CADENCE_ANNUAL:
        files.append((safe_file_name(f"{stem} Annual Report {report.label}.xlsx"), exports.workbook_bytes(exports.annual_sheets(report)), XLSX_TYPE))
    return files


# ------------------------------------------------------------------ sending

def send_period(profile, cadence, start, end, users=None):
    """Email one period to each user in ``users`` (default: the profile's sendable recipients). Returns ``(sent, problems)``; never raises."""
    from mailer import sender

    if users is None:
        users, problems = recipients(profile)
    else:
        problems = []
    if not users:
        return 0, problems + ["nobody to send to"]
    try:
        report = build_report(profile, cadence, start, end)
        year = build_year_to_date(profile, cadence, start, end)
        files = attachments(profile, cadence, report)
    except Exception as exc:  # a bad row or a busy lock: nothing can be sent for this period
        logger.warning("Report email for profile %s (%s) could not be made: %s", profile.pk, cadence, exc)
        return 0, problems + [f"the report could not be made: {exc}"]
    site = sender.site_name()
    subject = f"{site}: {CADENCE_LABELS[cadence].lower()} investments report, {_day(report.start)} to {_day(report.closing)}"
    sent = 0
    for user in users:
        try:
            message = sender.build_message(subject, body(recipient_name(user), report, cadence, site, year), [user.email])
            for name, data, content_type in files:
                message.attach(name, data, content_type)
            message.send(fail_silently=False)
            sent += 1
        except Exception as exc:
            logger.warning("Report email to user %s failed: %s", user.pk, exc)
            problems.append(f"{recipient_name(user)}: {exc}")
    return sent, problems


def _record(row, ok, text):
    row.last_attempt_at = timezone.now()
    row.last_ok = ok
    row.last_message = text[:500]
    row.save()


def send_due(row, today):
    """Send every cadence of ``row`` that is due. A period moves on once at least one person got it (so nobody gets it twice when only one
    address failed); the problems are kept on the row. Returns the number of emails sent."""
    total, notes, failed = 0, [], False
    for cadence, start, end in due(row, today):
        sent, problems = send_period(row.profile, cadence, start, end)
        label = CADENCE_LABELS[cadence]
        if sent:
            setattr(row, f"{cadence}_last_end", end)
            notes.append(f"{label} ({_day(start)} to {_day(end)}): sent to {sent}")
        notes += [f"{label}: {p}" for p in problems]
        total += sent
        if problems:
            failed = True
            PriceMaintenanceLog.objects.create(kind=LOG_KIND, ok=False, message=f"profile {row.profile_id} {cadence}: {'; '.join(problems)}"[:300])
    if notes:
        _record(row, not failed, ". ".join(notes) + ".")
    return total


def send_all(today=None):
    """The nightly run: every live Investments profile with a cadence ticked. Returns ``(emails sent, profiles with nothing due)``."""
    from accounts.models import Profile
    from accounts.suite import KEY_INVESTMENTS
    from mailer.services import is_configured

    today = today or timezone.localdate()
    if not is_configured():
        return 0, 0
    sent = idle = 0
    live = Profile.objects.filter(program=KEY_INVESTMENTS, deleted_at__isnull=True)
    for row in PeriodicEmail.objects.filter(profile__in=live).select_related("profile"):
        if not due(row, today):
            idle += 1
            continue
        try:
            sent += send_due(row, today)
        except Exception as exc:  # one profile's failure never stops the others
            logger.warning("Report emails for profile %s failed: %s", row.profile_id, exc)
            PriceMaintenanceLog.objects.create(kind=LOG_KIND, ok=False, message=f"profile {row.profile_id}: {exc}"[:300])
    return sent, idle


def send_now(profile, cadence, today=None):
    """The page's "Send now": email the latest ended period of ``cadence`` to the recipients at once. Does not move the schedule.
    Returns ``(ok, message)``."""
    from mailer.services import is_configured

    if not is_configured():
        return False, "Email is not set up on this server (EMAIL_HOST is missing)."
    today = today or timezone.localdate()
    start, end = latest_period(cadence, today)
    sent, problems = send_period(profile, cadence, start, end)
    text = f"{CADENCE_LABELS[cadence]} report for {_day(start)} to {_day(end)} sent to {sent} {'person' if sent == 1 else 'people'}."
    if problems:
        text += " Problems: " + "; ".join(problems) + "."
    row = PeriodicEmail.objects.filter(profile=profile).first()
    if row:
        _record(row, not problems and sent > 0, text)
    return (not problems and sent > 0), text
