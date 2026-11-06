"""Import of memos from a spreadsheet. Editors only."""
from django.views.decorators.http import require_GET

from fees.decorators import fees_editor, handle_fees_errors
from fees.pages import render_page


@fees_editor
@handle_fees_errors()
@require_GET
def import_page(request):
    return render_page(request, "fees/import.html")
