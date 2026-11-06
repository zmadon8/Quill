"""Import of memos from a spreadsheet, in two steps. Editors only.

Step 1 (``inspect``) reads the headers and a few sample rows and guesses which column is which. Step 2 (``run``)
imports with the mapping the user confirmed. The file is sent again with step 2, so the server keeps no upload
between requests. Both steps hold the one-at-a-time lock (``Busy`` gives the 503 page).
"""
from django.views.decorators.http import require_POST, require_safe

from fees import scope
from fees.decorators import fees_editor, handle_fees_errors
from fees.errors import FeesError
from fees.pages import render_page
from fees.services import imports


@fees_editor
@handle_fees_errors()
@require_safe
def import_page(request):
    return render_page(request, "fees/import.html")


def _upload(request):
    upload = request.FILES.get("file")
    if upload is None:
        raise FeesError("IMPORT_FAILED", "Choose a file to import.")
    return upload


@fees_editor
@handle_fees_errors(fallback="fees_import")
@require_POST
def inspect(request):
    upload = _upload(request)
    info = imports.inspect_file(upload)
    columns = [{"index": i, "name": name} for i, name in enumerate(info["headers"])]
    fields = [
        {"id": field_id, "label": label, "group": group, "required": required, "guess": info["mapping"].get(field_id) or ""}
        for field_id, label, group, required in imports.IMPORT_FIELDS
    ]
    return render_page(
        request,
        "fees/import_map.html",
        {"info": info, "columns": columns, "fields": fields, "file_name": upload.name},
    )


@fees_editor
@handle_fees_errors(fallback="fees_import")
@require_POST
def run(request):
    profile, _settings = scope.context(request)
    upload = _upload(request)
    mapping = {}
    for field_id, _label, _group, _required in imports.IMPORT_FIELDS:
        header = request.POST.get(f"map_{field_id}", "")
        mapping[field_id] = header or None
    result = imports.run_import(profile, upload, mapping, auto_number=request.POST.get("auto_number") == "1")
    return render_page(request, "fees/import_result.html", {"result": result})
