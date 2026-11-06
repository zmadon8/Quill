"""Payment pages: the new and edit forms and the payee suggestions. Editors only (design section 5)."""
from django.http import Http404
from django.views.decorators.http import require_GET

from fees import forms, scope
from fees.decorators import fees_editor, handle_fees_errors
from fees.pages import int_list, int_or_none, json_ok, render_page
from fees.models import Payment
from fees.services import memos, payments
from fees.services import settings as settings_service


def payment_or_404(profile, payment_id):
    """The payment dict for ``payment_id``; another profile's payment is a 404 (the service says 422)."""
    if not Payment.objects.filter(profile=profile, pk=payment_id).exists():
        raise Http404("Payment not found")
    return payments.get_payment(profile, payment_id)


def _form_page(request, form, payment=None, memo_id=None):
    profile, _settings = scope.context(request)
    return render_page(
        request,
        "fees/payment_form.html",
        {
            "form": form,
            "payment": payment,
            "memo_id": memo_id,
            "bank_choices": settings_service.list_bank_accounts(profile),
        },
    )


@fees_editor
@handle_fees_errors()
@require_GET
def payment_new(request):
    profile, _settings = scope.context(request)
    config = settings_service.get_settings(profile)
    memo = None
    prefill = None
    memo_id = int_or_none(request.GET.get("memo"))
    if memo_id is not None:
        memo = memos.get_memo(profile, memo_id)
        prefill = payments.payment_prefill(config["default_payment_amount"], memo["amount_due"], config["default_tds_rate"])
    return _form_page(request, forms.blank_payment_form(config, memo, prefill), memo_id=memo_id)


@fees_editor
@handle_fees_errors()
@require_GET
def payment_edit(request, payment_id):
    profile, _settings = scope.context(request)
    dto = payment_or_404(profile, payment_id)
    return _form_page(request, forms.payment_form_from_dto(dto), payment=dto)


@fees_editor
@handle_fees_errors(json=True)
@require_GET
def payees(request):
    """JSON: payee names used before on payments for the given matters (``?matters=1,2``)."""
    profile, _settings = scope.context(request)
    return json_ok({"payees": payments.payees_for_matters(profile, int_list(request.GET.get("matters")))})
