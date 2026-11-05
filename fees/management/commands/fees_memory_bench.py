"""Measure the real Fee Register memory baseline on a live-like instance (T1.6, R-NFR-7).

This is a manual tool, never wired into CI or ``manage.py test``. CI only needs it to import cleanly
(``manage.py check`` loads it); the authoritative RSS numbers come from a Render Shell run with the
owner's help, as the RAM budget (section 8 and 9) describes.

What it does:

* Reports the steady-state / import cost of the process: the startup RSS high-water mark from
  ``resource.getrusage(RUSAGE_SELF).ru_maxrss`` and the resident cost of importing ``openpyxl``
  (imported lazily, inside ``handle``, with RSS read before and after) so the "openpyxl resident"
  number in the RAM budget can be filled in.
* Builds the planning dataset (``fees.tests.datasets.build_planning_dataset``) in a throwaway fees
  profile inside a transaction that is rolled back, and reports the peak Python allocations of that
  build using the shared ``fees.tests.memory.assert_peak_under`` helper. Nothing is left behind.
* Prints a readable table of operation name, peak Python allocations (MB) and process RSS (MB), and
  exits non-zero if any measured peak exceeds its cap.

The heavy operations (statistics, dashboard, pivot, Excel export/import, suite restore, Word export)
are built in Phases 2 to 8; this skeleton keeps a registry so each phase can append its own
``(name, callable, cap_mb)`` entry without touching the reporting code. It does not import or call any
not-yet-existing service.

``openpyxl`` is imported lazily inside ``handle`` and never at module top, so loading this command
module (which ``manage.py check`` does) does not pull ``openpyxl`` into the worker.
"""
import argparse

try:  # ``resource`` is POSIX-only; on a platform without it the RSS columns read "n/a".
    import resource
except ImportError:  # pragma: no cover - platform dependent
    resource = None

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


# Planning-size defaults (RAM budget section 3 and 8). A unittest case shim so the shared
# ``assert_peak_under`` helper, which calls ``testcase.fail``, can be used outside a test run.
_PLANNING_MEMOS = 6000
_PLANNING_PAYMENTS = 8000
_PLANNING_ALLOCATIONS = 9000

# Generous caps for the skeleton. The dataset build is a bulk load, not a guarded heavy operation, so
# its cap is deliberately loose; Phase 2 onward will add the real per-operation caps from section 3.
_DATASET_BUILD_CAP_MB = 200.0


class _PeakFail(Exception):
    """Raised by the shim below when ``assert_peak_under`` reports a block over its cap."""


class _BenchCase:
    """A tiny stand-in for a ``TestCase`` so ``fees.tests.memory.assert_peak_under`` works here.

    ``assert_peak_under`` only ever calls ``testcase.fail(message)``; this turns that into an
    exception the command can catch and turn into a readable row plus a non-zero exit.
    """

    def fail(self, message):
        raise _PeakFail(message)


def _rss_mb():
    """Process peak RSS in MB from ``getrusage`` where available, else ``None``.

    ``ru_maxrss`` is kilobytes on Linux (what CI and Render measure) and bytes on macOS; this returns
    the Linux reading. It is a high-water mark, so it only ever rises during the run.
    """
    if resource is None:  # pragma: no cover - platform dependent
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


class Command(BaseCommand):
    help = (
        "Measure the real Fee Register memory baseline: startup RSS, the resident cost of importing "
        "openpyxl, and the peak allocations of building the planning dataset in a rolled-back "
        "transaction. Manual tool for Render Shell and local runs; it is never part of CI or "
        "manage.py test and it leaves no data behind."
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
        seed = options["seed"]
        skip_build = options["skip_build"]

        rows = []  # (operation name, peak Python allocations MB or None, process RSS MB or None)
        failures = []

        startup_rss = _rss_mb()
        rows.append(("startup (apps loaded, no openpyxl)", None, startup_rss))

        openpyxl_resident = self._measure_openpyxl_resident()
        rows.append(("openpyxl import (resident delta)", openpyxl_resident, _rss_mb()))

        if skip_build:
            self.stdout.write("Skipping the dataset build (--skip-build); import cost only.")
        else:
            for name, func, cap_mb in self._operations(memos, payments, allocations, seed):
                peak_mb, over = self._run_operation(name, func, cap_mb)
                rows.append((name, peak_mb, _rss_mb()))
                if over:
                    failures.append(name)

        self._print_table(rows)
        self._print_guidance()

        if failures:
            raise CommandError(
                "Peak over cap for: " + ", ".join(failures) + ". See the table above."
            )

    # -- dataset sizing ---------------------------------------------------------------------------

    def _resolve_sizes(self, options):
        """The (memos, payments, allocations) to build, after the --dataset-size shortcut."""
        if options["dataset_size"] == "small":
            return 200, 200, 200
        return options["memos"], options["payments"], options["allocations"]

    # -- operation registry -----------------------------------------------------------------------

    def _operations(self, memos, payments, allocations, seed):
        """The list of ``(name, callable, cap_mb)`` benchmarks.

        Today it is only the planning-dataset build. Phases 2 to 8 append their heavy operations here
        (statistics, dashboard, pivot, Excel export/import, suite restore, Word export) with the caps
        from RAM budget section 3, each measuring inside its own rolled-back transaction or against a
        dataset this command already built. Do not import not-yet-existing services at module top.
        """
        return [
            (
                "dataset build (planning size)",
                lambda: self._build_dataset(memos, payments, allocations, seed),
                _DATASET_BUILD_CAP_MB,
            ),
        ]

    def _build_dataset(self, memos, payments, allocations, seed):
        """Build the planning dataset in a throwaway profile inside a rolled-back transaction.

        ``transaction.set_rollback(True)`` marks the atomic block to roll back on exit, so every row
        created here (the profile and all its fee rows) is discarded and the command leaves the real
        instance exactly as it found it. Imports are local so loading the module stays cheap.
        """
        from accounts.models import Profile
        from accounts.suite import KEY_FEES
        from fees.tests.datasets import build_planning_dataset

        with transaction.atomic():
            profile = Profile.objects.create(
                program=KEY_FEES, name="__fees_memory_bench throwaway__"
            )
            summary = build_planning_dataset(
                profile,
                memos=memos,
                payments=payments,
                allocations=allocations,
                seed=seed,
            )
            self.stdout.write(
                "Built in a rolled-back transaction: "
                + ", ".join(f"{k}={v}" for k, v in summary.items())
            )
            transaction.set_rollback(True)

    def _run_operation(self, name, func, cap_mb):
        """Run one benchmark under ``assert_peak_under``; return (peak MB or None, over-cap bool)."""
        from fees.tests.memory import assert_peak_under

        case = _BenchCase()
        over = False
        peak_mb = None
        try:
            with assert_peak_under(case, cap_mb) as peak_box:
                func()
            peak_mb = peak_box[0]
        except _PeakFail as exc:
            over = True
            peak_mb = peak_box[0] if peak_box else None
            self.stderr.write(self.style.ERROR(f"{name}: {exc}"))
        return peak_mb, over

    # -- openpyxl resident cost -------------------------------------------------------------------

    def _measure_openpyxl_resident(self):
        """Resident RSS cost of importing ``openpyxl``, measured by reading RSS before and after.

        The import is lazy (here, never at module top) so this command module can be loaded without
        pulling ``openpyxl`` into a worker. Returns the RSS delta in MB, or ``None`` when ``resource``
        is unavailable. ``ru_maxrss`` is a high-water mark, so the delta is a floor on the true cost.
        """
        before = _rss_mb()
        try:
            import openpyxl  # noqa: F401  (imported only to measure its resident cost)
        except ImportError:
            self.stderr.write(
                self.style.WARNING("openpyxl is not installed; skipping its resident-cost measurement.")
            )
            return None
        after = _rss_mb()
        if before is None or after is None:
            return None
        return max(0.0, after - before)

    # -- reporting --------------------------------------------------------------------------------

    def _print_table(self, rows):
        """Print the operation / peak-allocations / RSS table in a fixed-width, readable layout."""
        self.stdout.write("")
        header = f"{'operation':44} {'peak alloc (MB)':>16} {'process RSS (MB)':>18}"
        self.stdout.write(header)
        self.stdout.write("-" * len(header))
        for name, peak_mb, rss_mb in rows:
            peak_text = f"{peak_mb:.1f}" if peak_mb is not None else "n/a"
            rss_text = f"{rss_mb:.0f}" if rss_mb is not None else "n/a"
            self.stdout.write(f"{name:44} {peak_text:>16} {rss_text:>18}")
        self.stdout.write("")

    def _print_guidance(self):
        """Repeat the decision rule so a Render Shell operator sees it next to the numbers."""
        self.stdout.write(
            "Decision rule (RAM budget section 7 and 9): if the worker baseline RSS is above 130 MB "
            "or the openpyxl resident delta is above 35 MB, apply the section 7 levers "
            "(MALLOC_ARENA_MAX=2, gunicorn --preload, or 1 worker with 4 threads). Each is a separate, "
            "owner-approved render.yaml or env change. Record the numbers in the 'Measured baseline' "
            "section of docs/FEES_RAM_BUDGET.md; do not fabricate them."
        )
