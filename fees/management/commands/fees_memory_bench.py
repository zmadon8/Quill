"""Measure the Fee Register's heavy operations against the RAM budget caps (T1.6, T9.3, R-NFR-7).

Run it on a machine with the project's requirements installed (CI after the tests, or a Render Shell)::

    python manage.py fees_memory_bench
    python manage.py fees_memory_bench --dataset-size small      # quick 200/200/200 run
    python manage.py fees_memory_bench --skip-build              # startup and openpyxl cost only

It builds the planning dataset (``fees.tests.datasets.build_planning_dataset``) in a throwaway fees
profile and times each heavy operation built since Phase 1: statistics, dashboard, pivot, Excel export,
annual summary, Word render, Excel import and Excel restore. Everything runs inside one transaction
that is rolled back at the end, so the command creates its own temporary profile and data, leaves
nothing behind and never reads or changes any other profile's data. Each operation runs inside its own
savepoint, so one failing operation cannot break the next.

Output is one machine-readable line per operation, then a final ``BENCH done`` line::

    BENCH <operation> rss_peak_mb=<x> tracemalloc_peak_mb=<y> cap_mb=<z> status=<OK|OVER|ERROR>

``tracemalloc_peak_mb`` is the peak of Python allocations inside the operation (the figure the caps in
docs/FEES_RAM_BUDGET.md section 3 are written against); ``status`` compares it with ``cap_mb``.
``rss_peak_mb`` is the whole process's ``ru_maxrss`` high-water mark after the operation, for
information, so it only ever rises through the run. Lines beginning ``INFO`` give the startup RSS and
the resident cost of importing ``openpyxl``. The command never prints environment variables or
settings. It exits non-zero if any operation is OVER or ERROR.

``openpyxl`` and the services are imported lazily, inside functions, so loading this module (which
``manage.py check`` does) does not pull ``openpyxl`` into the worker.
"""
import argparse

try:  # ``resource`` is POSIX-only; on a platform without it the RSS columns read "n/a".
    import resource
except ImportError:  # pragma: no cover - platform dependent
    resource = None

import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

# Planning-size defaults (RAM budget section 3 and 8).
_PLANNING_MEMOS = 6000
_PLANNING_PAYMENTS = 8000
_PLANNING_ALLOCATIONS = 9000
# Rows in the generated import file (the same size the import memory test uses).
_IMPORT_ROWS = 3000

# Caps in MB from RAM budget section 3. The dataset build is a bulk load, not a guarded heavy
# operation, so its cap is deliberately loose.
_CAPS = {
    "dataset_build": 200.0,
    "statistics": 5.0,
    "dashboard": 3.0,
    "pivot": 8.0,
    "excel_export": 12.0,
    "annual_summary": 20.0,
    "word_render": 2.0,
    "excel_import": 25.0,
    "excel_restore": 40.0,
}


class _PeakFail(Exception):
    """Raised by the shim below when ``assert_peak_under`` reports a block over its cap."""


class _BenchCase:
    """A tiny stand-in for a ``TestCase`` so ``fees.tests.memory.assert_peak_under`` works here.

    ``assert_peak_under`` only ever calls ``testcase.fail(message)``; this turns that into an
    exception the command can catch and report as an ``OVER`` line.
    """

    def fail(self, message):
        raise _PeakFail(message)


class _Rollback(Exception):
    """Raised at the end of the run to roll the whole transaction back and discard every bench row."""


def _rss_mb():
    """Process peak RSS in MB from ``getrusage`` where available, else ``None``.

    ``ru_maxrss`` is kilobytes on Linux (what CI and Render measure). It is a high-water mark, so it
    only ever rises during the run.
    """
    if resource is None:  # pragma: no cover - platform dependent
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _fmt(value):
    return f"{value:.1f}" if value is not None else "n/a"


def _import_rows(count):
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


def _sample_memo():
    """A fully filled memo dict for the Word placeholder map (same shape the Word tests use)."""
    import datetime
    from decimal import Decimal

    return {
        "date": datetime.date(2026, 7, 15),
        "memo_number": "2026-27/1",
        "addressee_line1": "Acme Legal",
        "addressee_line2": "Mumbai",
        "matter_name": "Acme v Beta",
        "matter_short_name": None,
        "court_name": "High Court",
        "plaintiff_name": "Acme",
        "plaintiff_type": "Plaintiff",
        "defendant_name": "",
        "defendant_type": "",
        "client": "Acme",
        "num_appearances": 2,
        "fees_per_appearance": Decimal("5000"),
        "fees_appearances": Decimal("10000"),
        "dates_of_appearances": "1 Jan",
        "num_conferences": 1,
        "fees_per_conference": Decimal("3000"),
        "fees_conferences": Decimal("3000"),
        "dates_of_conferences": "2 Jan",
        "misc_drafting_description": "Drafting",
        "fees_misc_drafting": Decimal("1000"),
        "total_fees": Decimal("14000"),
    }


class Command(BaseCommand):
    help = (
        "Measure peak memory of the Fee Register's heavy operations (statistics, dashboard, pivot, "
        "Excel export, annual summary, Word render, Excel import, Excel restore) on the planning "
        "dataset and compare each with its cap in docs/FEES_RAM_BUDGET.md. Builds its own temporary "
        "profile inside a transaction that is rolled back, so it leaves no data and touches no other "
        "profile. Prints one 'BENCH <operation> ...' line per operation and a final 'BENCH done'. "
        "Exits non-zero if any operation is over its cap."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--memos",
            type=int,
            default=_PLANNING_MEMOS,
            help=f"Memos to build (default {_PLANNING_MEMOS}, the planning size). Lower it for a quick run.",
        )
        parser.add_argument(
            "--payments",
            type=int,
            default=_PLANNING_PAYMENTS,
            help=f"Payments to build (default {_PLANNING_PAYMENTS}).",
        )
        parser.add_argument(
            "--allocations",
            type=int,
            default=_PLANNING_ALLOCATIONS,
            help=f"Allocations to build (default {_PLANNING_ALLOCATIONS}).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=0,
            help="Seed for the deterministic dataset generator (default 0).",
        )
        parser.add_argument(
            "--dataset-size",
            choices=["planning", "small"],
            default="planning",
            help="'small' overrides the counts with a quick 200/200/200 set for a fast smoke run.",
        )
        parser.add_argument(
            "--skip-build",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Only report the startup and openpyxl-import cost; do not build the dataset.",
        )

    def handle(self, *args, **options):
        memos, payments, allocations = self._resolve_sizes(options)
        self.sizes = (memos, payments, allocations, options["seed"])
        self.failures = []

        self.stdout.write(f"INFO startup_rss_mb={_fmt(_rss_mb())}")
        self.stdout.write(f"INFO openpyxl_resident_mb={_fmt(self._measure_openpyxl_resident())}")

        if not options["skip_build"]:
            with tempfile.TemporaryDirectory() as tmp:
                self.tmp = Path(tmp)
                try:
                    # One outer transaction for the whole run: every row the bench creates, in the
                    # throwaway profile only, is discarded when _Rollback leaves the block.
                    with transaction.atomic():
                        self._run_all()
                        raise _Rollback
                except _Rollback:
                    pass

        self.stdout.write("BENCH done")
        if self.failures:
            raise CommandError("Over cap or failed: " + ", ".join(self.failures))

    # -- dataset sizing ---------------------------------------------------------------------------

    def _resolve_sizes(self, options):
        """The (memos, payments, allocations) to build, after the --dataset-size shortcut."""
        if options["dataset_size"] == "small":
            return 200, 200, 200
        return options["memos"], options["payments"], options["allocations"]

    # -- the operations ---------------------------------------------------------------------------

    def _run_all(self):
        """Create the throwaway profiles, then run each operation in turn.

        Each entry is ``(name, prepare)``. ``prepare`` does the unmeasured set-up and returns the
        callable to measure. Excel restore is last because it replaces the planning profile's data.
        """
        from accounts.models import Profile
        from accounts.suite import KEY_FEES

        self.planning = Profile.objects.create(program=KEY_FEES, name="__fees_memory_bench planning__")
        self.import_profile = Profile.objects.create(program=KEY_FEES, name="__fees_memory_bench import__")
        steps = [
            ("dataset_build", self._prepare_build),
            ("statistics", self._prepare_statistics),
            ("dashboard", self._prepare_dashboard),
            ("pivot", self._prepare_pivot),
            ("excel_export", self._prepare_export),
            ("annual_summary", self._prepare_annual),
            ("word_render", self._prepare_word),
            ("excel_import", self._prepare_import),
            ("excel_restore", self._prepare_restore),
        ]
        built = False
        for name, prepare in steps:
            if name != "dataset_build" and not built:
                self._report(name, None, None, "ERROR")
                self.failures.append(name)
                continue
            if self._measure(name, prepare) and name == "dataset_build":
                built = True

    def _measure(self, name, prepare):
        """Prepare and measure one operation, print its BENCH line, return True if it ran cleanly."""
        from fees.tests.memory import assert_peak_under

        cap = _CAPS[name]
        peak = None
        status = "OK"
        try:
            with transaction.atomic():  # a savepoint: a failed operation cannot poison the next one
                func = prepare()
                case = _BenchCase()
                try:
                    with assert_peak_under(case, cap) as peak_box:
                        func()
                    peak = peak_box[0]
                except _PeakFail:
                    peak = peak_box[0]
                    status = "OVER"
        except Exception as exc:  # noqa: BLE001 - one broken operation must not stop the others
            status = "ERROR"
            self.stderr.write(f"{name}: {type(exc).__name__}: {exc}")
        self._report(name, peak, cap, status)
        if status != "OK":
            self.failures.append(name)
        return status != "ERROR"

    def _report(self, name, peak, cap, status):
        cap_text = _fmt(cap) if cap is not None else _fmt(_CAPS[name])
        self.stdout.write(
            f"BENCH {name} rss_peak_mb={_fmt(_rss_mb())} tracemalloc_peak_mb={_fmt(peak)} "
            f"cap_mb={cap_text} status={status}"
        )

    def _prepare_build(self):
        from fees.tests.datasets import build_planning_dataset

        memos, payments, allocations, seed = self.sizes

        def run():
            build_planning_dataset(
                self.planning, memos=memos, payments=payments, allocations=allocations, seed=seed
            )

        return run

    def _prepare_statistics(self):
        from fees.services.statistics import get_period_statistics

        return lambda: get_period_statistics(self.planning, "financialYear", None, {})

    def _prepare_dashboard(self):
        from fees.services import dashboard

        on = {
            "statistics_enabled": True,
            "overdue_days": 0,
            "initial_financial_year": "2015-16",
        }
        return lambda: dashboard.get_dashboard_kpis(self.planning, settings=on)

    def _prepare_pivot(self):
        from fees.services.statistics import get_pivot

        options = {"measure": "billed", "row_dim": "month", "col_dim": "financialYear"}
        return lambda: get_pivot(self.planning, options)

    def _prepare_export(self):
        from fees.services.excel_backup import export_workbook

        def run():
            out = export_workbook(self.planning)
            out.close()

        return run

    def _prepare_annual(self):
        from fees.exports import xlsx
        from fees.models import Memo

        fy = (
            Memo.objects.filter(profile=self.planning)
            .order_by("-financial_year")
            .values_list("financial_year", flat=True)
            .first()
        )

        def run():
            _name, out = xlsx.export_annual_summary(self.planning, fy)
            out.close()

        return run

    def _prepare_word(self):
        from fees.exports import images, template_prep, word
        from fees.exports.placeholders import build_placeholder_map
        from fees.tests import docx_support

        fixture = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "Template 2-11-2026 (short tags).docx"
        prepared, _tags = template_prep.prepare(fixture.read_bytes())
        mapping = build_placeholder_map(_sample_memo())
        data = docx_support.png_bytes(600, 200)
        content_type, extension, width, height = images.inspect_image(data)
        signature = word.Signature(content_type, extension, data, width, height)

        def run():
            out = word.render(prepared, mapping, signature)
            out.close()

        return run

    def _prepare_import(self):
        from openpyxl import Workbook

        from fees.services.imports import inspect_file, run_import

        memos = self.sizes[0]
        path = str(self.tmp / "bench_import.xlsx")
        workbook = Workbook(write_only=True)
        sheet = workbook.create_sheet()
        for row in _import_rows(min(_IMPORT_ROWS, max(memos, 1))):
            sheet.append(row)
        workbook.save(path)
        mapping = inspect_file(path)["mapping"]
        return lambda: run_import(self.import_profile, path, mapping)

    def _prepare_restore(self):
        from fees.services.excel_backup import export_workbook
        from fees.services.excel_restore import RESTORE_CONFIRMATION, restore_workbook

        out = export_workbook(self.planning)

        def run():
            try:
                # No safety backup: the throwaway profile has nothing worth keeping.
                restore_workbook(self.planning, out, RESTORE_CONFIRMATION, backup_func=lambda kind, user: None)
            finally:
                out.close()

        return run

    # -- openpyxl resident cost -------------------------------------------------------------------

    def _measure_openpyxl_resident(self):
        """Resident RSS cost of importing ``openpyxl``, measured by reading RSS before and after.

        The import is lazy (here, never at module top). Returns the RSS delta in MB, or ``None`` when
        ``resource`` or ``openpyxl`` is unavailable. ``ru_maxrss`` is a high-water mark, so the delta
        is a floor on the true cost.
        """
        before = _rss_mb()
        try:
            import openpyxl  # noqa: F401  (imported only to measure its resident cost)
        except ImportError:
            return None
        after = _rss_mb()
        if before is None or after is None:
            return None
        return max(0.0, after - before)
