"""Search everything (owner round 2026-11): one box, every program the user can open, results grouped by program.

Reuses each program's own search service: the Case Law Diary's ``diary.search.run_search``, the Fee Register's
``fees.services.search.search`` and Investments' ``investments.services.search.search``. Only the profile the user is working
in per program is searched, and a program that fails is skipped with a note, so one program can never break the page.
"""
import logging

from django.shortcuts import render
from django.urls import reverse

from accounts import programs
from accounts.permissions import reader_required
from accounts.profiles import request_profile
from accounts.suite import KEY_DIARY, KEY_FEES, KEY_INVESTMENTS, get_names

logger = logging.getLogger(__name__)

PER_PROGRAM = 8
MIN_LEN = 2


def _diary(request, profile, q):
    from accounts.models import ROLE_EDITOR
    from accounts.profiles import request_role
    from diary import page_search
    from diary.search import run_search

    pages = [{"title": p["title"], "subtitle": p["what"], "kind": "Page", "url": p["url"]}
             for p in page_search.page_results(q, request_role(request, KEY_DIARY) == ROLE_EDITOR, request.user.is_admin)]
    hits = run_search(profile, q)
    found = pages + [{"title": h.label, "subtitle": " \u203a ".join(name for name, _url in h.path), "kind": h.kind, "url": h.url} for h in hits[:PER_PROGRAM]]
    return len(pages) + len(hits), found[:PER_PROGRAM], reverse("search") + "?q=" + _quote(q)


def _fees(request, profile, q):
    from accounts.models import ROLE_EDITOR
    from accounts.profiles import request_role
    from fees.pages import dashboard_on
    from fees.services import settings as fees_settings
    from fees.services.search import search

    hits = search(profile, q, limit=50, can_edit=request_role(request, KEY_FEES) == ROLE_EDITOR,
                  statistics_on=dashboard_on(fees_settings.get_settings(profile)))
    urls = {"firm": "fees_firm_detail", "matter": "fees_matter_detail", "memo": "fees_memo_detail"}
    return len(hits), [{"title": h["title"], "subtitle": h.get("subtitle", ""), "kind": h["kind"].capitalize(),
                        "url": h.get("url") or reverse(urls[h["kind"]], args=[h["id"]])} for h in hits[:PER_PROGRAM]], \
        reverse("fees_search_page") + "?q=" + _quote(q)


def _investments(request, profile, q):
    from investments import pages
    from investments.services.search import search

    hits = search(profile, q, limit=PER_PROGRAM)
    out = []
    for h in hits:
        name, arg = h["url"]
        if name == "page":
            href = reverse(pages.url_name(arg))
        elif name == "transactions":
            href = reverse("investments_transactions") + f"?highlight={arg}#txn-{arg}"
        else:
            href = reverse(f"investments_{name}", args=[arg])
        out.append({"title": h["title"], "subtitle": h.get("subtitle", ""), "kind": h["kind"], "url": href})
    return len(hits), out, reverse("investments_search") + "?q=" + _quote(q)


def _quote(q):
    from urllib.parse import quote

    return quote(q)


@reader_required
def suite_search(request):
    q = request.GET.get("q", "").strip()[:200]
    names = get_names()
    sections = []
    wanted = ((KEY_DIARY, _diary, True), (KEY_FEES, _fees, programs.fees_enabled()),
              (KEY_INVESTMENTS, _investments, programs.investments_enabled()))
    searched = len(q) >= MIN_LEN
    for key, fn, enabled in wanted:
        if not enabled:
            continue
        profile = request_profile(request, key)
        if profile is None:
            continue
        section = {"key": key, "name": names.get(key, key), "results": [], "total": 0, "more": "", "failed": False}
        if searched:
            try:
                section["total"], section["results"], section["more"] = fn(request, profile, q)
            except Exception:  # one program must never break the page
                logger.exception("Search everything: %s failed", key)
                section["failed"] = True
        sections.append(section)
    return render(request, "suite_search.html", {
        "query": q, "sections": sections, "searched": searched, "too_short": 0 < len(q) < MIN_LEN,
        "total": sum(s["total"] for s in sections),
    })
