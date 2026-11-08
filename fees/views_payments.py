"""Payment pages: the new and edit forms, delete, assign, and the payee suggestions. Readers may open the new and edit forms (GET) but only an Editor may save; delete, assign and the payee
suggestions are Editor-only (design section 5)."""
from django.contrib import messages
from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_http_methods, require_safe, require_POST

from fees import forms, scope
from fees.decorators import fees_editor, fees_read_write, handle_fees_errors
from fees.errors import FeesError
from fees.models import Memo, Payment
from fees.pages import int_list, int_or_none, json_ok, render_page
from fees.services import memo_numbers, memos, payments
from fees.services import settings as settings_service
from fees.services.money import format_money

FORM_FIELDS = (
    "amount", "tds_rate", "auto_tds", "tds_amount", "date_of_payment", "payee", "bank_account_id",
    "payment_mode", "payment_details",
)


def payment_or_404(profile, payment_id):
    """The payment dict for ``payment_id``; another profile's payment is a 404 (the service says 422)."""
    if not Payment.objects.filter(profile=profile, pk=payment_id).exists():
        raise Http404("Payment not found")
    return payments.get_payment(profile, payment_id)


def _memo_ids(query):
    """The memos named in the query (``?memo=1&memo=2`` or ``?memo=1,2``), in order, no repeats, any number."""
    seen = []
    for value in query.getlist("memo"):
        for number in int_list(value):
            if number not in seen:
                seen.append(number)
    return seen


def memo_options(profile, memo_ids=(), numbers=(), money_unit="full"):
    """The memos a payment row can pick, from ONE query: ``(options, matter_ids)``.

    Options are the profile's numbered non-draft memos with an amount due and not written off, newest first,
    plus ``memo_ids`` (already allocated or named in ``?memo=``) and ``numbers`` (typed on a form that failed to
    save), whatever their state. The matters and firms of ``memo_ids`` are the form's known ones: their memos
    are listed first. ``matter_ids`` are those known matters, for the payee suggestions.
    """
    memo_ids = list(memo_ids)
    numbers = [n for n in numbers if n]
    wanted = Q(written_off=False, total_fees__gt=F("amount_paid"))
    if memo_ids:
        wanted |= Q(pk__in=memo_ids)
    if numbers:
        wanted |= Q(memo_number__in=numbers)
    rows = list(
        Memo.objects.filter(profile=profile, is_draft=False, memo_number__isnull=False)
        .filter(wanted)
        .order_by(F("date").desc(nulls_last=True), "-id")
        .values("id", "memo_number", "matter_id", "firm_id", "matter__name", "total_fees", "amount_paid")
    )
    known = [r for r in rows if r["id"] in memo_ids]
    matters = {r["matter_id"] for r in known}
    firms = {r["firm_id"] for r in known}
    first = [r for r in rows if r["matter_id"] in matters or r["firm_id"] in firms]
    rest = [r for r in rows if not (r["matter_id"] in matters or r["firm_id"] in firms)]
    options = []
    for r in first + rest:
        due = r["total_fees"] - r["amount_paid"]
        options.append(
            {
                "number": r["memo_number"],
                "due": str(due),
                "label": f"{r['memo_number']} \u00b7 {r['matter__name']} (Rs {format_money(due, unit=money_unit)} Due)",
            }
        )
    return options, sorted(matters)


def _form_page(request, form, payment=None, memo_ids=None, errors=None, status=200):
    profile, config = scope.context(request)
    memo_ids = list(memo_ids or [])
    if payment is not None:
        memo_ids = [a["memo_id"] for a in payment["allocations"]]
    unit = getattr(config, "money_unit", None) or "full"
    options, matter_ids = memo_options(
        profile, memo_ids, [row["memo_number"].strip() for row in form["rows"]], money_unit=unit
    )
    return render_page(
        request,
        "fees/payment_form.html",
        {
            "form": form,
            "memo_options": options,
            "payment": payment,
            "memo_id": memo_ids[0] if len(memo_ids) == 1 and payment is None else None,
            "memo_query": "&".join(f"memo={n}" for n in memo_ids) if payment is None else "",
            "matter_ids": ",".join(str(n) for n in matter_ids),
            "bank_choices": settings_service.list_bank_accounts(profile),
            "errors": errors or [],
        },
        status=status,
    )


def _echo(post):
    """What the user typed, in the shape the form template reads."""
    form = {name: post.get(name, "") for name in FORM_FIELDS}
    form["auto_tds"] = post.get("auto_tds") == "1"
    rows = [
        {
            "memo_number": post.get(f"alloc_memo_{i}", ""),
            "amount": post.get(f"alloc_amount_{i}", ""),
            "tds_amount": post.get(f"alloc_tds_{i}", ""),
        }
        for i in forms.posted_row_indexes(post)
    ]
    if post.get("add_row"):
        rows.append({"memo_number": "", "amount": "", "tds_amount": ""})
    form["rows"] = rows or forms.blank_rows()
    return form


def _after_save(request, dto):
    messages.success(request, "Payment saved.")
    allocations = dto["allocations"]
    if len(allocations) == 1:
        return redirect("fees_memo_detail", memo_id=allocations[0]["memo_id"])
    return redirect("fees_feebook")


def _data(request, profile):
    bank_ids = {account.pk for account in settings_service.list_bank_accounts(profile)}
    return forms.payment_data_from_post(request.POST, profile, bank_ids)


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def payment_new(request):
    profile, _settings = scope.context(request)
    memo_ids = _memo_ids(request.GET)
    if request.method == "POST" and request.POST.get("add_row"):
        return _form_page(request, _echo(request.POST), memo_ids=memo_ids)
    if request.method == "POST":
        try:
            dto = payments.add_payment(profile, _data(request, profile))
        except FeesError as err:
            if err.status == 404:
                raise Http404(err.message) from err
            return _form_page(request, _echo(request.POST), memo_ids=memo_ids, errors=[err.message], status=err.status)
        return _after_save(request, dto)
    config = settings_service.get_settings(profile)
    if not memo_ids:
        return _form_page(request, forms.blank_payment_form(config))
    found = [memos.get_memo(profile, n) for n in memo_ids]
    if len(found) == 1:
        prefill = payments.payment_prefill(config["default_payment_amount"], found[0]["amount_due"], config["default_tds_rate"])
        return _form_page(request, forms.blank_payment_form(config, found[0], prefill), memo_ids=memo_ids)
    return _form_page(request, forms.multi_memo_payment_form(config, found), memo_ids=memo_ids)


@fees_read_write
@handle_fees_errors()
@require_http_methods(["GET", "HEAD", "POST"])
def payment_edit(request, payment_id):
    profile, _settings = scope.context(request)
    dto = payment_or_404(profile, payment_id)
    if request.method == "POST" and request.POST.get("add_row"):
        return _form_page(request, _echo(request.POST), payment=dto)
    if request.method == "POST":
        try:
            dto = payments.update_payment(profile, payment_id, _data(request, profile))
        except FeesError as err:
            if err.status == 404:
                raise Http404(err.message) from err
            return _form_page(request, _echo(request.POST), payment=dto, errors=[err.message], status=err.status)
        return _after_save(request, dto)
    return _form_page(request, forms.payment_form_from_dto(dto), payment=dto)


@fees_editor
@handle_fees_errors()
@require_POST
def payment_delete(request, payment_id):
    profile, _settings = scope.context(request)
    payment_or_404(profile, payment_id)
    if request.POST.get("confirm") != "1":
        messages.error(request, "Tick the box to confirm that you want to delete this payment.")
        return redirect("fees_payment_edit", payment_id=payment_id)
    payments.delete_payment(profile, payment_id)
    messages.success(request, "Payment deleted.")
    return redirect("fees_feebook")


@fees_editor
@handle_fees_errors()
@require_POST
def payment_assign(request, payment_id):
    """Attach a payment to the memo whose number was typed (or whose id was sent), replacing its allocations."""
    profile, _settings = scope.context(request)
    payment_or_404(profile, payment_id)
    number = (request.POST.get("memo_number") or "").strip()
    memo_id = memo_numbers.find_memo_id_by_number(profile, number) if number else int_or_none(request.POST.get("memo_id"))
    if memo_id is None:
        raise FeesError("INVALID_PAYMENT", f'There is no numbered memo "{number}".' if number else "Enter a memo number.")
    payments.assign_payment_to_memo(profile, payment_id, memo_id)
    messages.success(request, "Payment attached to the memo.")
    return redirect("fees_feebook")


@fees_editor
@handle_fees_errors(json=True)
@require_safe
def payees(request):
    """JSON: payee names used before on payments for the given matters (``?matters=1,2``)."""
    profile, _settings = scope.context(request)
    return json_ok({"payees": payments.payees_for_matters(profile, int_list(request.GET.get("matters")))})
