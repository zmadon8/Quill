"""Memo import tests (T6.1, T6.2; R-IM-1 to R-IM-3, design 7, porting brief section 8).

Ports ``importService.test.ts`` (rows given as dicts to ``import_memos``) and adds: the mapping guess, number
and date parsing (impossible dates), the streaming readers (csv and ``.xlsx`` read-only, cell conversion,
formula cached results), the size, row, column and cell caps, the heavy lock, a spy proving the file is never
read whole, per-row rules and payment groups, one transaction and one ``data_version`` bump, owner isolation,
a seeded property loop and the memory gates (under 25 MB on a large generated file).

Memo numbers in the fixtures are not of the form ``YYYY-YY/N``: the Q8 rule (R-NUM-3) refuses a custom number
that looks like an automatic one, so the originals ``2025-26/1`` become ``INV-1`` here, and one test pins the
refusal.

Files are built with ``csv`` and ``openpyxl`` (write-only) in a temporary directory; ``openpyxl`` is imported
inside the helpers, like the application code.
"""
import contextlib
import datetime
import io
import os
import random
import re
import tempfile
import zipfile
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import SimpleTestCase, TestCase, tag
from django.test.utils import CaptureQueriesContext

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.errors import FeesError
from fees.models import Allocation, FeesSettings, Firm, Group, Matter, Memo, Payment
from fees.services import imports, matters, memo_fees, memos
from fees.services.heavy import Busy
from fees.services.imports import (
    DEFAULT_GROUP_NAME,
    guess_mapping,
    import_memos,
    inspect_file,
    iter_rows,
    parse_date,
    parse_number,
    run_import,
)
from fees.tests.memory import assert_peak_under

EM_DASH = "\u2014"

BASE_MAPPING = {
    "firm_name": "Firm",
    "matter_name": "Matter",
    "memo_number": "No",
    "date": "Date",
    "total_fees": "Total",
    "amount_paid": "Paid",
}


def fees_profile(name):
    return Profile.objects.create(program=KEY_FEES, name=name)


def write_csv(path, rows):
    import csv

    with open(path, "w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows(rows)


def write_xlsx(path, rows):
    from openpyxl import Workbook

    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet()
    for row in rows:
        sheet.append(row)
    workbook.save(path)


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
    'spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.'
    'spreadsheetml.worksheet+xml"/></Types>'
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    'officeDocument" Target="xl/workbook.xml"/></Relationships>'
)
_WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
)
_WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
    'worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
)


def write_formula_xlsx(path, rows, formulas):
    """A minimal workbook whose cells in ``formulas`` ({'C2': ('=A2*2', cached or None)}) are formulas.

    ``openpyxl`` cannot write a cached result, so the sheet XML is written by hand. ``rows`` is a list of
    lists of text or numbers (no formulas); formula cells overwrite the cell at that reference.
    """
    def ref(row_index, col_index):
        return f"{chr(ord('A') + col_index)}{row_index + 1}"

    xml_rows = []
    for r, row in enumerate(rows):
        cells = []
        for c, value in enumerate(row):
            name = ref(r, c)
            if name in formulas:
                formula, cached = formulas[name]
                body = f"<f>{formula.lstrip('=')}</f>" + (f"<v>{cached}</v>" if cached is not None else "")
                cells.append(f'<c r="{name}">{body}</c>')
            elif isinstance(value, (int, float)):
                cells.append(f'<c r="{name}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{name}" t="inlineStr"><is><t>{value}</t></is></c>')
        xml_rows.append(f'<row r="{r + 1}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
        + "".join(xml_rows)
        + "</sheetData></worksheet>"
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _CONTENT_TYPES)
        archive.writestr("_rels/.rels", _ROOT_RELS)
        archive.writestr("xl/workbook.xml", _WORKBOOK)
        archive.writestr("xl/_rels/workbook.xml.rels", _WORKBOOK_RELS)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def read_all(source, kind=None):
    with contextlib.closing(iter_rows(source, kind)) as rows:
        return list(rows)


class TempDirMixin:
    def make_dir(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class ParseTests(SimpleTestCase):
    def test_numbers_strip_rupee_commas_and_spaces(self):
        self.assertEqual(parse_number("\u20b9 1,20,000"), Decimal(120000))
        self.assertEqual(parse_number(" 12 345.50 "), Decimal("12345.50"))
        self.assertEqual(parse_number("-5"), Decimal(-5))
        self.assertEqual(parse_number("1e3"), Decimal(1000))

    def test_unparseable_numbers_are_zero(self):
        for text in ("", None, "abc", "12abc", "Infinity", "NaN", "--1", "1.2.3", "#N/A"):
            self.assertEqual(parse_number(text), Decimal(0), text)

    def test_iso_dates_with_a_time_part(self):
        self.assertEqual(parse_date("2025-06-10"), ("2025-06-10", False))
        self.assertEqual(parse_date("2025-06-10T00:00:00"), ("2025-06-10", False))
        self.assertEqual(parse_date(" 2024-02-29 "), ("2024-02-29", False))

    def test_day_first_slash_and_dash(self):
        self.assertEqual(parse_date("10/06/2025"), ("2025-06-10", False))
        self.assertEqual(parse_date("5-7-2025"), ("2025-07-05", False))
        self.assertEqual(parse_date("31/12/2025"), ("2025-12-31", False))

    def test_impossible_dates_are_blank_and_flagged(self):
        for text in ("31/02/2026", "2026-02-30", "2025-02-29", "00/01/2025", "15/13/2025", "2026-13-40"):
            self.assertEqual(parse_date(text), ("", True), text)

    def test_generic_formats_and_junk(self):
        self.assertEqual(parse_date("10 Jun 2025"), ("2025-06-10", False))
        self.assertEqual(parse_date("June 10, 2025"), ("2025-06-10", False))
        for text in ("", None, "junk", "tomorrow"):
            self.assertEqual(parse_date(text), ("", False), text)


class GuessTests(SimpleTestCase):
    def test_exact_headers_win_over_substrings(self):
        headers = ["Firm", "Partner", "Matter Name", "Memo No.", "Date", "Payment Date", "Total Fees",
                   "Amount Paid", "TDS", "Client", "Court", "Payee", "Payment Group"]
        guess = guess_mapping(headers)
        self.assertEqual(guess["firm_name"], "Firm")
        self.assertEqual(guess["partner_name"], "Partner")
        self.assertEqual(guess["matter_name"], "Matter Name")
        self.assertEqual(guess["memo_number"], "Memo No.")
        self.assertEqual(guess["date"], "Date")  # not "Payment Date"
        self.assertEqual(guess["payment_date"], "Payment Date")
        self.assertEqual(guess["total_fees"], "Total Fees")
        self.assertEqual(guess["amount_paid"], "Amount Paid")
        self.assertEqual(guess["payment_tds"], "TDS")
        self.assertEqual(guess["matter_client"], "Client")
        self.assertEqual(guess["court_name"], "Court")
        self.assertEqual(guess["payee"], "Payee")
        self.assertEqual(guess["payment_group"], "Payment Group")
        self.assertIsNone(guess["num_drafts"])
        self.assertIsNone(guess["party_plaintiff"])

    def test_case_and_substring_rules(self):
        guess = guess_mapping(["COMPANY NAME", "Case Title", "Invoice #", "No. of Appearances", "Rate"])
        self.assertEqual(guess["firm_name"], "COMPANY NAME")
        self.assertEqual(guess["matter_name"], "Case Title")
        self.assertEqual(guess["memo_number"], "Invoice #")
        self.assertEqual(guess["num_appearances"], "No. of Appearances")
        self.assertEqual(guess["fees_per_appearance"], "Rate")

    def test_every_field_has_an_entry(self):
        self.assertEqual(set(guess_mapping([])), {field[0] for field in imports.IMPORT_FIELDS})
        self.assertEqual(len(imports.IMPORT_FIELDS), 22)


# ---------------------------------------------------------------------------
# Streaming readers and caps
# ---------------------------------------------------------------------------

class CsvReaderTests(TempDirMixin, SimpleTestCase):
    def path(self, content, name="data.csv", mode="w"):
        path = os.path.join(self.make_dir(), name)
        if isinstance(content, bytes):
            with open(path, "wb") as handle:
                handle.write(content)
        else:
            with open(path, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
        return path

    def test_quoting_bom_crlf_and_blank_rows(self):
        text = '\ufeffFirm,Matter,Note\r\nAcme,"A v\r\nB","x,""y"""\r\n\r\n , ,\r\nB,M,z'
        rows = read_all(self.path(text))
        self.assertEqual(rows, [["Firm", "Matter", "Note"], ["Acme", "A v\r\nB", 'x,"y"'], ["B", "M", "z"]])

    def test_tiny_chunks_split_crlf_and_multibyte_characters(self):
        text = 'Firm,Matter\r\nCaf\u00e9 \u20b9,"two\r\nlines"\r\nB,M\r\n'
        with mock.patch.object(imports, "_CSV_CHUNK", 1):
            rows = read_all(self.path(text.encode("utf-8")))
        self.assertEqual(rows, [["Firm", "Matter"], ["Caf\u00e9 \u20b9", "two\r\nlines"], ["B", "M"]])

    def test_cells_are_trimmed_and_short_rows_are_kept(self):
        rows = read_all(self.path("a,b,c\n  1 , 2\n3,4,5,6\n"))
        self.assertEqual(rows, [["a", "b", "c"], ["1", "2"], ["3", "4", "5"]])

    def test_not_utf8_is_refused_with_a_clear_message(self):
        with self.assertRaises(FeesError) as caught:
            read_all(self.path(b"a,b\n\xff\xfe,2\n"))
        self.assertEqual(caught.exception.code, "IMPORT_FAILED")
        self.assertIn("UTF-8", caught.exception.message)


class XlsxReaderTests(TempDirMixin, SimpleTestCase):
    def test_first_sheet_dates_numbers_and_text(self):
        path = os.path.join(self.make_dir(), "data.xlsx")
        write_xlsx(path, [
            ["Firm", "Matter", "Date", "Total", "Qty", "Flag"],
            ["Acme", "A v B", datetime.datetime(2025, 6, 10, 0, 0), 120000, 2.5, True],
            [None, None, None, None, None, None],
            ["Beta", "C", datetime.date(2025, 7, 1), 1234.5, 3.0, False],
        ])
        rows = read_all(path)
        self.assertEqual(rows[0], ["Firm", "Matter", "Date", "Total", "Qty", "Flag"])
        self.assertEqual(rows[1], ["Acme", "A v B", "2025-06-10", "120000", "2.5", "true"])
        self.assertEqual(rows[2], ["Beta", "C", "2025-07-01", "1234.5", "3", "false"])
        self.assertEqual(len(rows), 3)  # the blank row is skipped

    def test_hyperlink_cell_reads_as_its_text(self):
        from openpyxl import Workbook

        path = os.path.join(self.make_dir(), "link.xlsx")
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Firm", "Matter"])
        sheet.append(["Acme", "Linked matter"])
        sheet["B2"].hyperlink = "https://example.com/matter"
        workbook.save(path)
        self.assertEqual(read_all(path)[1], ["Acme", "Linked matter"])

    def test_formula_cell_reads_as_its_cached_result(self):
        path = os.path.join(self.make_dir(), "formula.xlsx")
        write_formula_xlsx(
            path,
            [["Firm", "Matter", "Total"], ["Acme", "M", 0], ["Beta", "N", 0]],
            {"C2": ("=40000+80000", 120000), "C3": ("=1+1", None)},
        )
        rows = read_all(path)
        self.assertEqual(rows[1], ["Acme", "M", "120000"])  # the cached result, not "=40000+80000"
        self.assertEqual(rows[2], ["Beta", "N", ""])  # a formula never calculated reads as blank
        self.assertFalse(any("=" in cell for row in rows for cell in row))

    def test_only_the_first_sheet_is_read(self):
        from openpyxl import Workbook

        path = os.path.join(self.make_dir(), "two.xlsx")
        workbook = Workbook()
        workbook.active.append(["Firm", "Matter"])
        workbook.active.append(["First", "Sheet"])
        second = workbook.create_sheet("Other")
        second.append(["Firm", "Matter"])
        second.append(["Second", "Sheet"])
        workbook.save(path)
        self.assertEqual(read_all(path), [["Firm", "Matter"], ["First", "Sheet"]])

    def test_a_damaged_xlsx_is_refused(self):
        path = os.path.join(self.make_dir(), "broken.xlsx")
        with open(path, "wb") as handle:
            handle.write(b"PK\x03\x04 this is not a real workbook")
        with self.assertRaises(FeesError) as caught:
            read_all(path)
        self.assertEqual(caught.exception.code, "IMPORT_FAILED")


class CapTests(TempDirMixin, SimpleTestCase):
    def csv_path(self, rows):
        path = os.path.join(self.make_dir(), "caps.csv")
        write_csv(path, rows)
        return path

    def assertFails(self, call, fragment=None):
        with self.assertRaises(FeesError) as caught:
            call()
        self.assertEqual(caught.exception.code, "IMPORT_FAILED")
        if fragment:
            self.assertIn(fragment, caught.exception.message)

    def test_size_cap_is_checked_before_the_file_is_opened(self):
        path = self.csv_path([["a", "b"], ["1", "2"]])
        with mock.patch.object(imports, "MAX_IMPORT_BYTES", 5), mock.patch("builtins.open") as opener:
            self.assertFails(lambda: iter_rows(path), "10 MB")
            opener.assert_not_called()

    def test_the_cap_is_ten_megabytes(self):
        self.assertEqual(imports.MAX_IMPORT_BYTES, 10 * 1024 * 1024)

    def test_row_cap(self):
        path = self.csv_path([["a"]] + [[str(i)] for i in range(5)])
        with mock.patch.object(imports, "MAX_IMPORT_ROWS", 4):
            self.assertFails(lambda: read_all(path), "rows")
        with mock.patch.object(imports, "MAX_IMPORT_ROWS", 5):
            self.assertEqual(len(read_all(path)), 6)  # exactly at the cap is allowed

    def test_column_cap(self):
        path = self.csv_path([["c%d" % i for i in range(6)], ["x"] * 6])
        with mock.patch.object(imports, "MAX_IMPORT_COLUMNS", 5):
            self.assertFails(lambda: read_all(path), "columns")
        with mock.patch.object(imports, "MAX_IMPORT_COLUMNS", 6):
            self.assertEqual(len(read_all(path)[0]), 6)

    def test_cell_cap(self):
        path = self.csv_path([["a"], ["x" * 20]])
        with mock.patch.object(imports, "MAX_CELL_CHARS", 10):
            self.assertFails(lambda: read_all(path), "characters")

    def test_xlsx_row_and_column_caps(self):
        path = os.path.join(self.make_dir(), "caps.xlsx")
        write_xlsx(path, [["a", "b", "c"]] + [[str(i), "x", "y"] for i in range(5)])
        with mock.patch.object(imports, "MAX_IMPORT_ROWS", 4):
            self.assertFails(lambda: read_all(path), "rows")
        with mock.patch.object(imports, "MAX_IMPORT_COLUMNS", 2):
            self.assertFails(lambda: read_all(path), "columns")

    def test_wrong_extension_empty_file_and_unknown_kind(self):
        directory = self.make_dir()
        text = os.path.join(directory, "data.txt")
        with open(text, "w") as handle:
            handle.write("a,b\n1,2\n")
        self.assertFails(lambda: iter_rows(text), ".xlsx and .csv")
        empty = os.path.join(directory, "empty.csv")
        open(empty, "w").close()
        self.assertFails(lambda: iter_rows(empty), "empty")
        self.assertFails(lambda: iter_rows(io.BytesIO(b"a,b\n")), ".xlsx and .csv")  # no name, no kind
        self.assertEqual(read_all(io.BytesIO(b"a,b\n1,2\n"), kind="csv"), [["a", "b"], ["1", "2"]])

    def test_zip_bomb_guard_for_xlsx(self):
        path = os.path.join(self.make_dir(), "bomb.xlsx")
        write_xlsx(path, [["a"], ["1"]])
        with mock.patch.object(imports, "MAX_UNCOMPRESSED_BYTES", 10):
            self.assertFails(lambda: iter_rows(path), "100 MB")


# ---------------------------------------------------------------------------
# Streaming proof: the file is never read whole
# ---------------------------------------------------------------------------

class SpyUpload(SimpleUploadedFile):
    """An upload that records every ``read`` call. A bare ``read()`` or ``read(-1)`` would load it whole."""

    def __init__(self, name, content):
        super().__init__(name, content)
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)


class StreamingSpyTests(TempDirMixin, SimpleTestCase):
    def assertBoundedReads(self, upload):
        self.assertTrue(upload.read_sizes, "the file was never read")
        for size in upload.read_sizes:
            self.assertIsInstance(size, int)
            self.assertGreaterEqual(size, 0, "read() with no size or -1 loads the whole file")

    def test_csv_is_read_in_bounded_chunks_never_with_read_all(self):
        text = "a,b\n" + "".join(f"{i},row{i}\n" for i in range(5000))
        upload = SpyUpload("big.csv", text.encode("utf-8"))
        with mock.patch.object(imports, "_CSV_CHUNK", 1024):
            rows = read_all(upload)
        self.assertEqual(len(rows), 5001)
        self.assertBoundedReads(upload)
        self.assertLessEqual(max(upload.read_sizes), 1024)
        self.assertGreater(len(upload.read_sizes), 5)  # many small reads, not one big one

    def test_xlsx_is_read_by_the_zip_reader_with_sizes_only(self):
        path = os.path.join(self.make_dir(), "big.xlsx")
        write_xlsx(path, [["a", "b"]] + [[i, f"row{i}"] for i in range(2000)])
        with open(path, "rb") as handle:
            upload = SpyUpload("big.xlsx", handle.read())
        rows = read_all(upload)
        self.assertEqual(len(rows), 2001)
        self.assertBoundedReads(upload)

    def test_run_import_reads_the_upload_with_sizes_only(self):
        text = "Firm,Matter\n" + "".join(f"F{i % 3},M{i}\n" for i in range(50))
        upload = SpyUpload("rows.csv", text.encode("utf-8"))
        # A fake runner proves the reader is lazy: the engine sees dict rows one at a time.
        seen = []
        with mock.patch.object(imports, "import_memos", lambda profile, rows, mapping, auto: seen.extend(rows) or {}):
            with mock.patch.object(imports, "heavy_operation", lambda name: contextlib.nullcontext()):
                run_import(None, upload, {"firm_name": "Firm", "matter_name": "Matter"})
        self.assertEqual(len(seen), 50)
        self.assertBoundedReads(upload)

    def test_the_module_never_calls_read_without_a_size(self):
        import inspect

        source = inspect.getsource(imports)
        self.assertIsNone(re.search(r"\.read\(\s*\)", source), "a bare read() would load the whole upload")
        self.assertIsNone(re.search(r"\.read\(\s*-1\s*\)", source))
        self.assertIsNone(re.search(r"\.readlines\(", source))

    def test_openpyxl_is_imported_lazily(self):
        import inspect

        source = inspect.getsource(imports)
        top_level = [line for line in source.splitlines() if re.match(r"(import|from)\s+openpyxl", line)]
        self.assertEqual(top_level, [])
        self.assertIn("    from openpyxl import load_workbook", source)

    def test_source_has_no_em_dash_and_no_second_fee_rule(self):
        import inspect

        source = inspect.getsource(imports)
        self.assertNotIn(EM_DASH, source)
        self.assertIsNone(re.search(r"num_appearances\s*\*\s*fees_per_appearance", source))
        self.assertIsNone(re.search(r"num_conferences\s*\*\s*fees_per_conference", source))


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

class InspectTests(TempDirMixin, SimpleTestCase):
    def test_headers_first_five_rows_count_and_guess(self):
        path = os.path.join(self.make_dir(), "in.csv")
        write_csv(path, [[" Firm ", "Matter Name ", "Amount Paid"]] + [[f"F{i}", f"M{i}", str(i)] for i in range(8)])
        result = inspect_file(path)
        self.assertEqual(result["headers"], ["Firm", "Matter Name", "Amount Paid"])
        self.assertEqual(len(result["sample_rows"]), 5)
        self.assertEqual(result["sample_rows"][0], ["F0", "M0", "0"])
        self.assertEqual(result["row_count"], 8)
        self.assertEqual(result["mapping"]["firm_name"], "Firm")
        self.assertEqual(result["mapping"]["matter_name"], "Matter Name")
        self.assertEqual(result["mapping"]["amount_paid"], "Amount Paid")

    def test_short_rows_are_padded_in_the_sample(self):
        path = os.path.join(self.make_dir(), "in.csv")
        write_csv(path, [["Firm", "Matter", "Note"], ["A", "B"]])
        self.assertEqual(inspect_file(path)["sample_rows"], [["A", "B", ""]])

    def test_header_only_and_empty_files_are_refused(self):
        directory = self.make_dir()
        header_only = os.path.join(directory, "h.csv")
        write_csv(header_only, [["Firm", "Matter"], [], ["", ""]])
        with self.assertRaises(FeesError) as caught:
            inspect_file(header_only)
        self.assertEqual(caught.exception.code, "IMPORT_FAILED")
        self.assertIn("at least one data row", caught.exception.message)
        blank = os.path.join(directory, "b.csv")
        write_csv(blank, [[""], []])
        with self.assertRaises(FeesError):
            inspect_file(blank)

    def test_xlsx_inspect(self):
        path = os.path.join(self.make_dir(), "in.xlsx")
        write_xlsx(path, [["Firm", "Matter", "Date"], ["A", "B", datetime.date(2025, 6, 10)]])
        result = inspect_file(path)
        self.assertEqual(result["sample_rows"], [["A", "B", "2025-06-10"]])
        self.assertEqual(result["row_count"], 1)

    def test_inspect_takes_the_heavy_lock(self):
        path = os.path.join(self.make_dir(), "in.csv")
        write_csv(path, [["Firm", "Matter"], ["A", "B"]])
        names = []

        @contextlib.contextmanager
        def recording(name):
            names.append(name)
            yield

        with mock.patch.object(imports, "heavy_operation", recording):
            inspect_file(path)
        self.assertEqual(names, ["excel_import"])

        @contextlib.contextmanager
        def busy(name):
            raise Busy()
            yield  # pragma: no cover

        with mock.patch.object(imports, "heavy_operation", busy):
            with self.assertRaises(Busy):
                inspect_file(path)


# ---------------------------------------------------------------------------
# The engine (port of importService.test.ts and the per-row rules of B 8)
# ---------------------------------------------------------------------------

class ImportMemosTests(TestCase):
    def setUp(self):
        self.profile = fees_profile("import-main")

    def memo_by_number(self, number):
        return Memo.objects.get(profile=self.profile, memo_number=number)

    def test_creates_firms_matters_numbered_memos_and_payments_from_rows(self):
        rows = [
            {"Firm": "Acme Co", "Matter": "Acme v Beta", "No": "INV-1", "Date": "10/06/2025", "Total": "1,20,000", "Paid": "20000"},
            {"Firm": "Acme Co", "Matter": "Acme v Beta", "No": "INV-2", "Date": "2025-07-01", "Total": "80000", "Paid": "0"},
            {"Firm": "Delta LLP", "Matter": "Delta Estate", "No": "INV-5", "Date": "15/08/2025", "Total": "50000", "Paid": "50000"},
        ]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(result["memos_created"], 3)
        self.assertEqual(result["firms_created"], 2)
        self.assertEqual(result["matters_created"], 2)
        self.assertEqual(result["payments_created"], 2)
        self.assertEqual(result["rows_processed"], 3)
        self.assertEqual(result["warnings"], [])
        numbers = sorted(Memo.objects.filter(profile=self.profile).values_list("memo_number", flat=True))
        self.assertEqual(numbers, ["INV-1", "INV-2", "INV-5"])
        acme1 = self.memo_by_number("INV-1")
        self.assertEqual(acme1.total_fees, Decimal("120000.00"))
        self.assertEqual(acme1.date, datetime.date(2025, 6, 10))
        self.assertEqual(acme1.addressee_line1, "Acme Co")
        self.assertFalse(acme1.is_draft)
        self.assertEqual(acme1.seq, 0)  # a custom number
        delta = self.memo_by_number("INV-5")
        self.assertEqual(delta.amount_received, Decimal("50000.00"))
        self.assertEqual(delta.amount_paid, delta.total_fees)  # fully paid
        self.assertEqual(self.memo_by_number("INV-2").amount_paid, Decimal("0.00"))

    def test_q8_a_number_that_looks_automatic_is_refused_for_that_row(self):
        rows = [
            {"Firm": "F", "Matter": "M", "No": "2025-26/1", "Date": "2025-06-10", "Total": "1000", "Paid": "0"},
            {"Firm": "F", "Matter": "M", "No": "INV-2", "Date": "2025-06-11", "Total": "1000", "Paid": "0"},
        ]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(result["memos_created"], 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertTrue(result["warnings"][0].startswith("Row 2: "))
        self.assertIn("automatic number", result["warnings"][0])

    def test_reuses_an_existing_firm_and_matter_case_insensitively(self):
        rows = [
            {"Firm": "Acme Co", "Matter": "Case A", "No": "1", "Date": "2025-06-10", "Total": "1000", "Paid": "0"},
            {"Firm": "acme co", "Matter": "case a", "No": "2", "Date": "2025-06-11", "Total": "2000", "Paid": "0"},
        ]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(result["firms_created"], 1)
        self.assertEqual(result["matters_created"], 1)
        self.assertEqual(Firm.objects.filter(profile=self.profile).count(), 1)
        # An existing firm and matter from before the import are reused too.
        again = import_memos(self.profile, [
            {"Firm": "ACME CO", "Matter": "CASE A", "No": "3", "Date": "2025-06-12", "Total": "5", "Paid": "0"}], BASE_MAPPING)
        self.assertEqual((again["firms_created"], again["matters_created"]), (0, 0))
        self.assertEqual(Matter.objects.filter(profile=self.profile).count(), 1)

    def test_rows_without_a_memo_number_import_as_drafts(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "", "Date": "2025-06-10", "Total": "1000", "Paid": "0"}]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        memo = Memo.objects.get(profile=self.profile)
        self.assertTrue(memo.is_draft)
        self.assertIsNone(memo.memo_number)
        self.assertEqual(memo.total_fees, Decimal("1000.00"))
        self.assertEqual(result["memos_created"], 1)

    def test_firm_and_matter_must_be_mapped(self):
        for mapping in ({"firm_name": "Firm"}, {"matter_name": "Matter"}, {}, {"firm_name": None, "matter_name": "M"}):
            with self.assertRaises(FeesError) as caught:
                import_memos(self.profile, [], mapping)
            self.assertEqual(caught.exception.code, "IMPORT_FAILED")
        with self.assertRaises(FeesError):
            import_memos(self.profile, [], {"firm_name": "F", "matter_name": "M", "no_such_field": "X"})

    def test_auto_number_numbers_in_row_order_per_financial_year(self):
        rows = [
            {"Firm": "F", "Matter": "M", "Date": "2025-06-10", "Total": "1000"},
            {"Firm": "F", "Matter": "M", "Date": "2025-06-10", "Total": "1000"},
            {"Firm": "F", "Matter": "M", "Date": "2025-08-01", "Total": "1000"},
            {"Firm": "F", "Matter": "M", "Date": "2026-05-01", "Total": "1000"},
        ]
        mapping = {"firm_name": "Firm", "matter_name": "Matter", "date": "Date", "total_fees": "Total"}
        result = import_memos(self.profile, rows, mapping, auto_number=True)
        self.assertEqual(result["memos_created"], 4)
        numbers = list(Memo.objects.filter(profile=self.profile).order_by("pk").values_list("memo_number", flat=True))
        self.assertEqual(numbers, ["2025-26/1", "2025-26/2", "2025-26/3", "2026-27/1"])
        self.assertFalse(Memo.objects.filter(profile=self.profile, seq=0).exists())  # none is custom

    def test_auto_number_still_makes_a_draft_without_a_valid_date(self):
        rows = [{"Firm": "F", "Matter": "M", "Date": "", "Total": "1000"},
                {"Firm": "F", "Matter": "M", "Date": "31/02/2026", "Total": "1000"}]
        mapping = {"firm_name": "Firm", "matter_name": "Matter", "date": "Date", "total_fees": "Total"}
        import_memos(self.profile, rows, mapping, auto_number=True)
        self.assertEqual(Memo.objects.filter(profile=self.profile, is_draft=True).count(), 2)

    def test_without_auto_number_an_unmapped_number_is_a_draft(self):
        rows = [{"Firm": "F", "Matter": "M", "Date": "2025-06-10", "Total": "1000"}]
        mapping = {"firm_name": "Firm", "matter_name": "Matter", "date": "Date", "total_fees": "Total"}
        import_memos(self.profile, rows, mapping)
        self.assertTrue(Memo.objects.get(profile=self.profile).is_draft)

    def test_number_of_drafts_when_mapped(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "INV-9", "Date": "2025-06-10", "Total": "1000", "Paid": "0", "Drafts": "3"}]
        import_memos(self.profile, rows, {**BASE_MAPPING, "num_drafts": "Drafts"})
        self.assertEqual(Memo.objects.get(profile=self.profile).num_drafts, 3)

    def test_unaccounted_payment_row(self):
        rows = [
            {"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-06-10", "Total": "1000", "Paid": "0", "Payee": ""},
            {"Firm": "", "Matter": "", "No": "", "Date": "2025-06-15", "Total": "", "Paid": "5000", "Payee": "Mr X", "Tds": "500", "PD": ""},
        ]
        result = import_memos(self.profile, rows, {**BASE_MAPPING, "payee": "Payee", "payment_tds": "Tds", "payment_date": "PD"})
        self.assertEqual(result["memos_created"], 1)
        self.assertEqual(result["payments_created"], 1)
        self.assertEqual(result["rows_processed"], 2)
        payment = Payment.objects.get(profile=self.profile)
        self.assertEqual(Allocation.objects.filter(profile=self.profile).count(), 0)
        self.assertEqual(payment.amount, Decimal("5000.00"))
        self.assertEqual(payment.tds_amount, Decimal("500.00"))
        self.assertFalse(payment.auto_tds)
        self.assertEqual(payment.payee, "Mr X")
        self.assertEqual(payment.date_of_payment, datetime.date.today())  # blank payment date means today

    def test_unaccounted_payment_needs_all_three_blank_and_a_positive_amount(self):
        rows = [
            {"Firm": "", "Matter": "", "No": "", "Date": "", "Total": "", "Paid": "0"},
            {"Firm": "", "Matter": "", "No": "", "Date": "", "Total": "", "Paid": "-5"},
            {"Firm": "", "Matter": "", "No": "INV-3", "Date": "", "Total": "", "Paid": "100"},
        ]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(result["payments_created"], 0)
        self.assertEqual(result["warnings"], [f"Row {n}: skipped (missing firm or matter name)." for n in (2, 3, 4)])

    def test_payment_group_merges_rows_into_one_split_payment(self):
        rows = [
            {"Firm": "F", "Matter": "M", "No": "INV-56", "Date": "2025-07-01", "Total": "20000", "Paid": "18000", "Tds": "2000", "PayDate": "2025-11-27", "Grp": "G1", "Payee": "First"},
            {"Firm": "F", "Matter": "M", "No": "INV-83", "Date": "2025-08-01", "Total": "30000", "Paid": "27000", "Tds": "3000", "PayDate": "2025-12-01", "Grp": "G1", "Payee": "Second"},
            {"Firm": "F", "Matter": "M", "No": "INV-98", "Date": "2025-09-01", "Total": "25000", "Paid": "22500", "Tds": "2500", "PayDate": "2025-11-27", "Grp": "G1", "Payee": ""},
            {"Firm": "F", "Matter": "M", "No": "INV-120", "Date": "2025-10-01", "Total": "10000", "Paid": "9000", "Tds": "1000", "PayDate": "2025-12-05", "Grp": "", "Payee": ""},
            {"Firm": "F", "Matter": "M", "No": "INV-121", "Date": "2025-10-02", "Total": "10000", "Paid": "9000", "Tds": "1000", "PayDate": "2025-12-06", "Grp": "G2", "Payee": ""},
        ]
        mapping = {**BASE_MAPPING, "payment_tds": "Tds", "payment_date": "PayDate", "payment_group": "Grp", "payee": "Payee"}
        result = import_memos(self.profile, rows, mapping)
        self.assertEqual(result["memos_created"], 5)
        self.assertEqual(result["payments_created"], 3)  # G1 split, single, one-member G2
        self.assertEqual(Payment.objects.filter(profile=self.profile).count(), 3)
        self.assertEqual(Allocation.objects.filter(profile=self.profile).count(), 5)
        split = Payment.objects.get(profile=self.profile, amount=Decimal("67500.00"))
        self.assertEqual(split.tds_amount, Decimal("7500.00"))
        self.assertEqual(split.date_of_payment, datetime.date(2025, 11, 27))  # from the first member
        self.assertEqual(split.payee, "First")
        self.assertEqual(split.allocations.count(), 3)
        self.assertEqual(
            sorted(split.allocations.values_list("memo__memo_number", flat=True)), ["INV-56", "INV-83", "INV-98"]
        )
        for number, net, tds in (("INV-56", "18000.00", "2000.00"), ("INV-83", "27000.00", "3000.00")):
            memo = self.memo_by_number(number)
            self.assertEqual(memo.amount_received, Decimal(net))
            self.assertEqual(memo.amount_tds, Decimal(tds))
            self.assertEqual(memo.amount_paid, memo.total_fees)
        single = self.memo_by_number("INV-120")
        self.assertEqual(Allocation.objects.get(memo=single).payment.allocations.count(), 1)
        one_member = self.memo_by_number("INV-121")
        self.assertEqual(Allocation.objects.get(memo=one_member).payment.date_of_payment, datetime.date(2025, 12, 6))

    def test_groups_are_matched_by_exact_string(self):
        rows = [
            {"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "100", "Paid": "100", "Grp": "g1"},
            {"Firm": "F", "Matter": "M", "No": "INV-2", "Date": "2025-07-01", "Total": "100", "Paid": "100", "Grp": "G1"},
        ]
        result = import_memos(self.profile, rows, {**BASE_MAPPING, "payment_group": "Grp"})
        self.assertEqual(result["payments_created"], 2)

    def test_payment_date_defaults_to_the_memo_date(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "100", "Paid": "60"}]
        import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(Payment.objects.get(profile=self.profile).date_of_payment, datetime.date(2025, 7, 1))

    def test_paid_amount_on_a_draft_is_ignored_with_a_warning(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "", "Date": "2025-07-01", "Total": "100", "Paid": "60"}]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(result["payments_created"], 0)
        self.assertEqual(result["warnings"], ["Row 2: paid amount ignored because the memo is a draft (no number)."])

    def test_a_number_with_no_valid_date_becomes_a_draft_with_a_warning(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "INV-7", "Date": "garbage", "Total": "100", "Paid": "0"}]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        memo = Memo.objects.get(profile=self.profile)
        self.assertTrue(memo.is_draft)
        self.assertIsNone(memo.memo_number)
        self.assertEqual(memo.date, datetime.date.today())
        self.assertEqual(result["warnings"], ['Row 2: memo "INV-7" has no valid date, imported as draft.'])

    def test_impossible_dates_warn_and_read_as_blank(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "INV-7", "Date": "31/02/2026", "Total": "100", "Paid": "40", "PD": "2026-02-30"},
                {"Firm": "F", "Matter": "M", "No": "INV-8", "Date": "2026-03-01", "Total": "100", "Paid": "40", "PD": "30/02/2026"}]
        result = import_memos(self.profile, rows, {**BASE_MAPPING, "payment_date": "PD"})
        warnings = result["warnings"]
        self.assertTrue(any(w.startswith("Row 2:") and "31/02/2026" in w for w in warnings))
        self.assertTrue(any(w.startswith("Row 3:") and "30/02/2026" in w for w in warnings))
        # The second row's payment date was blank, so it falls back to the memo date.
        self.assertEqual(Payment.objects.get(profile=self.profile).date_of_payment, datetime.date(2026, 3, 1))
        self.assertEqual(result["memos_created"], 2)

    def test_default_group_is_an_em_dash_and_partners_are_found_or_created(self):
        rows = [
            {"Firm": "F", "Matter": "M1", "No": "INV-1", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Partner": ""},
            {"Firm": "F", "Matter": "M2", "No": "INV-2", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Partner": "Mr Shah"},
            {"Firm": "F", "Matter": "M3", "No": "INV-3", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Partner": "MR SHAH"},
        ]
        import_memos(self.profile, rows, {**BASE_MAPPING, "partner_name": "Partner"})
        firm = Firm.objects.get(profile=self.profile)
        names = sorted(Group.objects.filter(firm=firm).values_list("name", flat=True))
        self.assertEqual(names, sorted([EM_DASH, "Mr Shah"]))  # no group named after the firm
        self.assertEqual(DEFAULT_GROUP_NAME, EM_DASH)
        self.assertEqual(Matter.objects.get(profile=self.profile, name="M3").group.name, "Mr Shah")

    def test_an_existing_matter_is_reused_even_under_another_group(self):
        rows = [
            {"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Partner": "A"},
            {"Firm": "F", "Matter": "M", "No": "INV-2", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Partner": "B"},
        ]
        result = import_memos(self.profile, rows, {**BASE_MAPPING, "partner_name": "Partner"})
        self.assertEqual(result["matters_created"], 1)
        self.assertEqual(Matter.objects.get(profile=self.profile).group.name, "A")
        self.assertFalse(Group.objects.filter(profile=self.profile, name="B").exists())

    def test_court_and_client_fill_a_matter_only_when_blank(self):
        rows = [
            {"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Court": "", "Client": "Cl 1"},
            {"Firm": "F", "Matter": "M", "No": "INV-2", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Court": "High Court", "Client": "Cl 2"},
            {"Firm": "F", "Matter": "M", "No": "INV-3", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Court": "Other", "Client": "Cl 3"},
        ]
        import_memos(self.profile, rows, {**BASE_MAPPING, "court_name": "Court", "matter_client": "Client"})
        matter = Matter.objects.get(profile=self.profile)
        self.assertEqual((matter.court_name, matter.client), ("High Court", "Cl 1"))
        self.assertEqual(self.memo_by_number("INV-1").client, "Cl 1")  # memos snapshot their own row
        self.assertEqual(self.memo_by_number("INV-2").court_name, "High Court")

    def test_total_column_overrides_the_breakup_and_unmapped_total_uses_it(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "777", "Paid": "0",
                 "NA": "2", "FA": "5,000", "NC": "1", "FC": "3000", "Misc": "1000", "Desc": "Drafting"}]
        breakup = {"num_appearances": "NA", "fees_per_appearance": "FA", "num_conferences": "NC",
                   "fees_per_conference": "FC", "fees_misc": "Misc", "misc_description": "Desc"}
        import_memos(self.profile, rows, {**BASE_MAPPING, **breakup})
        memo = Memo.objects.get(profile=self.profile)
        self.assertEqual(memo.total_fees, Decimal("777.00"))
        self.assertEqual(memo.custom_total_fees, Decimal("777.00"))
        self.assertEqual(memo.misc_drafting_description, "Drafting")
        memo.delete()
        no_total = {k: v for k, v in {**BASE_MAPPING, **breakup}.items() if k != "total_fees"}
        import_memos(self.profile, [{**rows[0], "No": "INV-2"}], no_total)
        memo = Memo.objects.get(profile=self.profile)
        self.assertIsNone(memo.custom_total_fees)
        self.assertEqual(memo.total_fees, Decimal("14000.00"))
        self.assertEqual(memo.total_fees, memo_fees.resolve_memo_fees(memo).total_fees)  # the single fee rule

    def test_parties_are_copied_to_the_memo(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "1", "Paid": "0", "Pl": "P Ltd", "Df": "D Ltd"}]
        import_memos(self.profile, rows, {**BASE_MAPPING, "party_plaintiff": "Pl", "party_defendant": "Df"})
        memo = Memo.objects.get(profile=self.profile)
        self.assertEqual((memo.plaintiff_name, memo.defendant_name), ("P Ltd", "D Ltd"))

    def test_row_numbers_are_index_plus_two_and_bad_rows_are_skipped(self):
        rows = [
            {"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "1", "Paid": "0"},
            {"Firm": "", "Matter": "M", "No": "INV-2", "Date": "2025-07-01", "Total": "1", "Paid": "0"},
            {"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "1", "Paid": "0"},
            {"Firm": "F", "Matter": "M", "No": "INV-4", "Date": "2025-07-01", "Total": "-5", "Paid": "0"},
            {"Firm": "F", "Matter": "M" * 151, "No": "INV-5", "Date": "2025-07-01", "Total": "1", "Paid": "0"},
            {"Firm": "F", "Matter": "M", "No": "INV-6", "Date": "2025-07-01", "Total": "1", "Paid": "0"},
        ]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(result["memos_created"], 2)
        self.assertEqual(result["warnings_total"], 4)
        self.assertEqual(result["warnings"][0], "Row 3: skipped (missing firm or matter name).")
        self.assertTrue(result["warnings"][1].startswith("Row 4: "))
        self.assertIn("already in use", result["warnings"][1])
        self.assertTrue(result["warnings"][2].startswith("Row 5: "))
        self.assertTrue(result["warnings"][3].startswith("Row 6: skipped, the matter name is longer than 150"))

    def test_archived_matter_row_is_skipped_with_the_service_message(self):
        import_memos(self.profile, [{"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "1", "Paid": "0"}], BASE_MAPPING)
        matters.archive_matter(self.profile, Matter.objects.get(profile=self.profile).pk)
        result = import_memos(self.profile, [{"Firm": "F", "Matter": "M", "No": "INV-2", "Date": "2025-07-01", "Total": "1", "Paid": "0"},
                                              {"Firm": "F", "Matter": "M", "No": "", "Date": "2025-07-01", "Total": "1", "Paid": "0"}], BASE_MAPPING)
        self.assertEqual(result["memos_created"], 1)  # only the draft, which needs no active matter
        self.assertEqual(result["warnings"], ["Row 2: Memos can only be created for Active Matters"])

    def test_oversize_numbers_skip_the_row_instead_of_crashing(self):
        rows = [
            {"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "9" * 30, "Paid": "0"},
            {"Firm": "F", "Matter": "M", "No": "INV-2", "Date": "2025-07-01", "Total": "5", "Paid": "9" * 30},
        ]
        result = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(result["memos_created"], 0)
        self.assertEqual(result["warnings_total"], 2)
        # A breakup whose product would not fit the money columns is refused as well.
        big = [{"Firm": "F", "Matter": "M", "No": "INV-3", "Date": "2025-07-01", "NA": "999999", "FA": "9999999999"}]
        mapping = {**BASE_MAPPING, "num_appearances": "NA", "fees_per_appearance": "FA", "total_fees": None, "amount_paid": None}
        result = import_memos(self.profile, big, mapping)
        self.assertEqual(result["memos_created"], 0)
        self.assertIn("too large", result["warnings"][0])

    def test_fractional_counts_are_rounded_with_a_warning(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "1", "Paid": "0", "NA": "2.5"}]
        result = import_memos(self.profile, rows, {**BASE_MAPPING, "num_appearances": "NA"})
        self.assertEqual(Memo.objects.get(profile=self.profile).num_appearances, 2)
        self.assertEqual(len(result["warnings"]), 1)

    def test_no_de_duplication_a_second_import_creates_everything_again(self):
        rows = [{"Firm": "F", "Matter": "M", "No": "", "Date": "2025-07-01", "Total": "100", "Paid": "0"},
                {"Firm": "", "Matter": "", "No": "", "Date": "", "Total": "", "Paid": "300"}]
        first = import_memos(self.profile, rows, BASE_MAPPING)
        second = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual((first["memos_created"], second["memos_created"]), (1, 1))
        self.assertEqual((first["firms_created"], second["firms_created"]), (1, 0))
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), 2)
        self.assertEqual(Payment.objects.filter(profile=self.profile).count(), 2)

    def test_one_transaction_an_unexpected_error_rolls_everything_back(self):
        rows = [{"Firm": f"F{i}", "Matter": "M", "No": f"INV-{i}", "Date": "2025-07-01", "Total": "10", "Paid": "5"} for i in range(4)]
        real = memos.create_memo
        calls = []

        def flaky(profile, data, is_draft=False):
            calls.append(1)
            if len(calls) == 3:
                raise RuntimeError("boom")
            return real(profile, data, is_draft)

        before = FeesSettings.objects.filter(profile=self.profile).values_list("data_version", flat=True).first()
        with mock.patch.object(memos, "create_memo", flaky):
            with self.assertRaises(RuntimeError):
                import_memos(self.profile, rows, BASE_MAPPING)
        for model in (Firm, Matter, Memo, Payment, Allocation, Group):
            self.assertEqual(model.objects.filter(profile=self.profile).count(), 0, model.__name__)
        after = FeesSettings.objects.filter(profile=self.profile).values_list("data_version", flat=True).first()
        self.assertEqual(before, after)

    def test_data_version_is_bumped_exactly_once(self):
        rows = [{"Firm": f"F{i}", "Matter": "M", "No": f"INV-{i}", "Date": "2025-07-01", "Total": "10", "Paid": "5", "Grp": "G"}
                for i in range(6)]
        memos.touch(self.profile)  # make sure the settings row exists
        before = FeesSettings.objects.get(profile=self.profile).data_version
        import_memos(self.profile, rows, {**BASE_MAPPING, "payment_group": "Grp"})
        self.assertEqual(FeesSettings.objects.get(profile=self.profile).data_version, before + 1)

    def test_other_profiles_are_untouched_and_names_are_not_shared(self):
        other = fees_profile("import-other")
        import_memos(other, [{"Firm": "Acme", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "10", "Paid": "10"}], BASE_MAPPING)
        result = import_memos(self.profile, [{"Firm": "Acme", "Matter": "M", "No": "INV-1", "Date": "2025-07-01", "Total": "10", "Paid": "10"}], BASE_MAPPING)
        self.assertEqual((result["firms_created"], result["matters_created"], result["memos_created"]), (1, 1, 1))
        self.assertEqual(Firm.objects.filter(profile=other).count(), 1)
        self.assertEqual(Memo.objects.filter(profile=other).count(), 1)
        self.assertEqual(Payment.objects.filter(profile=other).count(), 1)

    def test_warning_list_is_capped_but_the_total_is_counted(self):
        rows = [{"Firm": "", "Matter": "", "No": "", "Date": "", "Total": "", "Paid": "0"} for _ in range(30)]
        with mock.patch.object(imports, "MAX_WARNINGS", 10):
            result = import_memos(self.profile, rows, BASE_MAPPING)
        self.assertEqual(len(result["warnings"]), 10)
        self.assertEqual(result["warnings_total"], 30)

    def test_queries_per_row_stay_bounded_when_firm_and_matter_repeat(self):
        def rows(n, start):
            return [{"Firm": "F", "Matter": "M", "No": f"INV-{start + i}", "Date": "2025-07-01", "Total": "10", "Paid": "5"}
                    for i in range(n)]

        import_memos(self.profile, rows(1, 0), BASE_MAPPING)  # warm the firm and matter
        with CaptureQueriesContext(connection) as small:
            import_memos(self.profile, rows(10, 100), BASE_MAPPING)
        with CaptureQueriesContext(connection) as large:
            import_memos(self.profile, rows(30, 200), BASE_MAPPING)
        per_row_small = len(small) / 10
        per_row_large = len(large) / 30
        self.assertLessEqual(per_row_large, per_row_small + 2)  # no growth per row
        self.assertLessEqual(per_row_large, 60)  # a loose ceiling, not an exact count


# ---------------------------------------------------------------------------
# run_import over real files, the heavy lock and the mapping check
# ---------------------------------------------------------------------------

class RunImportTests(TempDirMixin, TestCase):
    HEADER = ["Firm", "Matter", "Memo No.", "Date", "Total Fees", "Amount Paid", "Payment Group"]

    def setUp(self):
        self.profile = fees_profile("run-import")
        self.directory = self.make_dir()

    def sample_rows(self):
        return [
            self.HEADER,
            ["Acme Co", "Acme v Beta", "INV-1", "10/06/2025", "1,20,000", "20000", ""],
            ["Acme Co", "Acme v Beta", "INV-2", "2025-07-01", "80000", "80000", "G1"],
            ["Delta LLP", "Delta Estate", "INV-3", "15/08/2025", "50000", "50000", "G1"],
        ]

    def check_sample_result(self, result):
        self.assertEqual(
            {k: result[k] for k in ("firms_created", "matters_created", "memos_created", "payments_created", "rows_processed")},
            {"firms_created": 2, "matters_created": 2, "memos_created": 3, "payments_created": 2, "rows_processed": 3},
        )
        self.assertEqual(Allocation.objects.filter(profile=self.profile).count(), 3)

    def test_csv_end_to_end_with_the_guessed_mapping(self):
        path = os.path.join(self.directory, "memos.csv")
        write_csv(path, self.sample_rows())
        mapping = inspect_file(path)["mapping"]
        self.check_sample_result(run_import(self.profile, path, mapping))

    def test_xlsx_end_to_end_with_real_date_cells(self):
        path = os.path.join(self.directory, "memos.xlsx")
        rows = self.sample_rows()
        rows[1][3] = datetime.datetime(2025, 6, 10)
        rows[1][4] = 120000
        write_xlsx(path, rows)
        mapping = inspect_file(path)["mapping"]
        self.check_sample_result(run_import(self.profile, path, mapping))
        self.assertEqual(Memo.objects.get(profile=self.profile, memo_number="INV-1").date, datetime.date(2025, 6, 10))
        self.assertEqual(Memo.objects.get(profile=self.profile, memo_number="INV-1").total_fees, Decimal("120000.00"))

    def test_xlsx_formula_total_uses_the_cached_result(self):
        path = os.path.join(self.directory, "formula.xlsx")
        write_formula_xlsx(
            path,
            [["Firm", "Matter", "Memo No.", "Total Fees"], ["F", "M", "INV-1", 0]],
            {"D2": ("=40000+80000", 120000)},
        )
        run_import(self.profile, path, {"firm_name": "Firm", "matter_name": "Matter", "memo_number": "Memo No.", "total_fees": "Total Fees"})
        self.assertEqual(Memo.objects.get(profile=self.profile).total_fees, Decimal("120000.00"))

    def test_an_uploaded_file_object_works(self):
        path = os.path.join(self.directory, "memos.csv")
        write_csv(path, self.sample_rows())
        with open(path, "rb") as handle:
            upload = SimpleUploadedFile("memos.csv", handle.read())
        self.check_sample_result(run_import(self.profile, upload, guess_mapping(self.HEADER)))

    def test_mapping_must_name_columns_in_the_file(self):
        path = os.path.join(self.directory, "memos.csv")
        write_csv(path, self.sample_rows())
        with self.assertRaises(FeesError) as caught:
            run_import(self.profile, path, {"firm_name": "Firm", "matter_name": "No such column"})
        self.assertIn("No such column", caught.exception.message)
        with self.assertRaises(FeesError):
            run_import(self.profile, path, {"firm_name": "Firm"})
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), 0)

    def test_header_only_file_changes_nothing(self):
        path = os.path.join(self.directory, "h.csv")
        write_csv(path, [self.HEADER])
        with self.assertRaises(FeesError):
            run_import(self.profile, path, guess_mapping(self.HEADER))
        self.assertFalse(FeesSettings.objects.filter(profile=self.profile).exists())

    def test_a_file_over_a_cap_changes_nothing(self):
        path = os.path.join(self.directory, "memos.csv")
        write_csv(path, self.sample_rows() + [["F", "M", "", "", "", "", ""]] * 5)
        with mock.patch.object(imports, "MAX_IMPORT_ROWS", 4):
            with self.assertRaises(FeesError):
                run_import(self.profile, path, guess_mapping(self.HEADER))
        # The cap trips while streaming, inside the single transaction, so nothing is left behind.
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), 0)
        self.assertEqual(Firm.objects.filter(profile=self.profile).count(), 0)

    def test_heavy_lock_is_taken_and_busy_propagates_without_changes(self):
        path = os.path.join(self.directory, "memos.csv")
        write_csv(path, self.sample_rows())
        names = []

        @contextlib.contextmanager
        def recording(name):
            names.append(name)
            yield

        with mock.patch.object(imports, "heavy_operation", recording):
            run_import(self.profile, path, guess_mapping(self.HEADER))
        self.assertEqual(names, ["excel_import"])

        @contextlib.contextmanager
        def busy(name):
            raise Busy()
            yield  # pragma: no cover

        count = Memo.objects.filter(profile=self.profile).count()
        with mock.patch.object(imports, "heavy_operation", busy):
            with self.assertRaises(Busy):
                run_import(self.profile, path, guess_mapping(self.HEADER))
        self.assertEqual(Memo.objects.filter(profile=self.profile).count(), count)


# ---------------------------------------------------------------------------
# A seeded property loop: stored values always equal values recomputed from the allocations
# ---------------------------------------------------------------------------

class ImportPropertyTests(TestCase):
    def test_random_files_leave_consistent_totals(self):
        for seed in range(20):
            rng = random.Random(seed)
            profile = fees_profile(f"prop-{seed}")
            rows = []
            for index in range(rng.randint(5, 25)):
                total = rng.randint(1, 50000)
                net = rng.randint(0, total)
                rows.append({
                    "Firm": rng.choice(["Alpha", "beta", "Gamma", ""]),
                    "Matter": rng.choice(["M1", "m2", "M3", ""]),
                    "No": rng.choice([f"INV-{seed}-{index}", f"INV-{seed}-{index}", ""]),
                    "Date": rng.choice(["2025-06-10", "11/07/2025", "31/02/2025", "", "2026-01-05"]),
                    "Total": str(total),
                    "Paid": str(net),
                    "Tds": str(rng.randint(0, 100)),
                    "Grp": rng.choice(["", "", "A", "B"]),
                })
            mapping = {**BASE_MAPPING, "payment_tds": "Tds", "payment_group": "Grp"}
            result = import_memos(profile, rows, mapping, auto_number=bool(seed % 2))
            self.assertEqual(Memo.objects.filter(profile=profile).count(), result["memos_created"], seed)
            for memo in Memo.objects.filter(profile=profile):
                allocations = list(Allocation.objects.filter(memo=memo))
                net = sum((a.amount for a in allocations), Decimal(0))
                tds = sum((a.tds_amount for a in allocations), Decimal(0))
                self.assertEqual((memo.amount_received, memo.amount_tds, memo.amount_paid),
                                 (net, tds, net + tds), (seed, memo.pk))
                self.assertEqual(memo.total_fees, memo_fees.resolve_memo_fees(memo).total_fees, (seed, memo.pk))
                if memo.is_draft:
                    self.assertEqual(allocations, [])
            for payment in Payment.objects.filter(profile=profile):
                allocated = Allocation.objects.filter(payment=payment)
                if allocated.exists():
                    self.assertEqual(sum((a.amount for a in allocated), Decimal(0)), payment.amount, seed)


# ---------------------------------------------------------------------------
# Memory gates (R-NFR-7): the 25 MB budget for an import
# ---------------------------------------------------------------------------

def _large_rows(count):
    yield ["Firm", "Partner", "Matter", "Memo No.", "Date", "Total Fees", "Amount Paid", "Payment Date", "Payment Group", "Client"]
    for index in range(count):
        yield [
            f"Firm {index % 60}",
            f"Partner {index % 3}",
            f"Matter {index % 400}",
            f"INV-{index}",
            f"{(index % 28) + 1:02d}/{(index % 12) + 1:02d}/2025",
            "12,000",
            "10800" if index % 2 == 0 else "0",
            "2025-12-01",
            f"G{index // 50}" if index % 5 == 0 else "",
            f"Client {index % 400}",
        ]


@tag("memory")
class ReaderMemoryTests(TempDirMixin, SimpleTestCase):
    def test_reading_the_row_cap_of_a_csv_peaks_under_25_mb(self):
        path = os.path.join(self.make_dir(), "cap.csv")
        write_csv(path, _large_rows(imports.MAX_IMPORT_ROWS))
        with assert_peak_under(self, 25):
            with contextlib.closing(iter_rows(path)) as rows:
                count = sum(1 for _ in rows)
        self.assertEqual(count, imports.MAX_IMPORT_ROWS + 1)

    def test_reading_a_large_xlsx_peaks_under_25_mb(self):
        path = os.path.join(self.make_dir(), "big.xlsx")
        write_xlsx(path, _large_rows(20000))
        with assert_peak_under(self, 25):
            with contextlib.closing(iter_rows(path)) as rows:
                count = sum(1 for _ in rows)
        self.assertEqual(count, 20001)


@tag("memory")
class ImportMemoryTests(TempDirMixin, TestCase):
    ROWS = 3000

    def check(self, path):
        profile = fees_profile("mem-import")
        mapping = inspect_file(path)["mapping"]
        self.assertEqual(mapping["firm_name"], "Firm")
        with assert_peak_under(self, 25):
            result = run_import(profile, path, mapping)
        self.assertEqual(result["memos_created"], self.ROWS)
        self.assertEqual(result["warnings_total"], 0, result["warnings"][:5])
        self.assertEqual(Memo.objects.filter(profile=profile).count(), self.ROWS)
        self.assertEqual(Firm.objects.filter(profile=profile).count(), 60)
        self.assertEqual(Matter.objects.filter(profile=profile).count(), 1200)  # 60 firms x 400 names, lcm 1200
        self.assertEqual(Payment.objects.filter(profile=profile).count(), result["payments_created"])
        self.assertGreater(Allocation.objects.filter(profile=profile).count(), result["payments_created"])

    def test_xlsx_import_peaks_under_25_mb(self):
        path = os.path.join(self.make_dir(), "large.xlsx")
        write_xlsx(path, _large_rows(self.ROWS))
        self.check(path)

    def test_csv_import_peaks_under_25_mb(self):
        path = os.path.join(self.make_dir(), "large.csv")
        write_csv(path, _large_rows(self.ROWS))
        self.check(path)
