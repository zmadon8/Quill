"""Payment pages: the new and edit forms, delete, assign, and the payee suggestions. Editors only (design section 5)."""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from fees import forms, scope
from fees.decorators import fees_editor, handle_fees_errors
from fees.errors import FeesError
from fees.models import Payment
from fees.pages import int_list, int_or_none, json_ok, render_page
from fees.services import memo_numbers, memos, payments
from fees.services import settings as settings_service

FORM_FIELDS = (
    "amount", "tds_rate", "auto_tds", "tds_amount", "date_of_payment", "payee", "bank_account_id",
    "payment_mode", "payment_details",
) + tuple(f"alloc_{kind}_{i}" for i in range(forms.PAYMENT_ROWS) for kind in ("memo", "amount", "tds"))


def payment_or_404(profile, payment_id):
    """The payment dict for ``payment_id``; another profile's payment is a 404 (the service says 422)."""
    if not Payment.objects.filter(profile=profile, pk=payment_id).exists():
        raise Http404("Payment not found")
    return payments.get_payment(profile, payment_id)


def _form_page(request, form, payment=None, memo_id=None, errors=None, status=200):
    profile, _settings = scope.context(request)
    return render_page(
        request,
        "fees/payment_form.html",
        {
            "form": form,
            "payment": payment,
            "memo_id": memo_id,
            "bank_choices": settings_service.list_bank_accounts(profile),
            "errors": errors or [],
        },
        status=status,
    )


def _echo(post):
    """What the user typed, in the shape the form template reads."""
    form = {name: post.get(name, "") for name in FORM_FIELDS}
    form["auto_tds"] = post.get("auto_tds") == "1"
    form["rows"] = [
        {
            "memo_number": post.get(f"alloc_memo_{i}", ""),
            "amount": post.get(f"alloc_amount_{i}", ""),
            "tds_amount": post.get(f"alloc_tds_{i}", ""),
        }
        for i in range(forms.PAYMENT_ROWS)
    ]
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


@fees_editor
@handle_fees_errors()
@require_http_methods(["GET", "POST"])
def payment_new(request):
    profile, _settings = scope.context(request)
    memo_id = int_or_none(request.GET.get("memo"))
    if request.method == "POST":
        try:
            dto = payments.add_payment(profile, _data(request, profile))
        except FeesError as err:
            if err.status == 404:
                raise Http404(err.message) from err
            return _form_page(request, _echo(request.POST), memo_id=memo_id, errors=[err.message], status=err.status)
        return _after_save(request, dto)
    config = settings_service.get_settings(profile)
    memo = None
    prefill = None
    if memo_id is not None:
        memo = memos.get_memo(profile, memo_id)
        prefill = payments.payment_prefill(config["default_payment_amount"], memo["amount_due"], config["default_tds_rate"])
    return _form_page(request, forms.blank_payment_form(config, memo, prefill), memo_id=memo_id)


@fees_editor
@handle_fees_errors()
@require_http_methods(["GET", "POST"])
def payment_edit(request, payment_id):
    profile, _settings = scope.context(request)
    dto = payment_or_404(profile, payment_id)
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
@require_GET
def payees(request):
    """JSON: payee names used before on payments for the given matters (``?matters=1,2``)."""
    profile, _settings = scope.context(request)
    return json_ok({"payees": payments.payees_for_matters(profile, int_list(request.GET.get("matters")))})
