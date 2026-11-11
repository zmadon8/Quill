"""Measure peak memory of the Investments program's operations against the plan's budget (plan 26.2 rule 9, section 31).

Run it where the project's requirements are installed (CI after the tests, or a Render Shell)::

    python manage.py investments_memory_bench
    python manage.py investments_memory_bench --dataset-size small

It builds a throwaway profile and user inside a transaction that is rolled back at the end, runs each registered
operation (``investments.bench``) inside its own savepoint, and prints one machine-readable line per operation::

    BENCH <operation> rss_peak_mb=<x> tracemalloc_peak_mb=<y> cap_mb=<z> seconds=<t> queries=<n> status=<OK|OVER|ERROR>

then ``BENCH done``. ``tracemalloc_peak_mb`` is the figure the caps are written against; ``rss_peak_mb`` is the process
high-water mark, for information. The command never prints settings or environment variables and it exits non-zero if
any operation is OVER or ERROR (CI runs it non-blocking, like the Fee Register's bench).
"""
import time
import traceback

try:  # POSIX only; on other platforms the RSS column reads n/a.
    import resource
except ImportError:  # pragma: no cover
    resource = None

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from fees.tests.memory import assert_peak_under


class _PeakFail(Exception):
    pass


class _BenchCase:
    """Stand-in for a TestCase: ``assert_peak_under`` only calls ``fail``."""

    def fail(self, message):
        raise _PeakFail(message)


class _Rollback(Exception):
    pass


def _rss_mb():
    if resource is None:  # pragma: no cover
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _fmt(value):
    return f"{value:.1f}" if value is not None else "n/a"


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def add_arguments(self, parser):
        parser.add_argument("--dataset-size", choices=["planning", "small"], default="planning")
        parser.add_argument("--seed", type=int, default=0)
        parser.add_argument("--only", action="append", help="Run only the operation with this name (repeat for several; dataset_build is needed first).")
        parser.add_argument("--timing-only", action="store_true", help="Do not trace memory (tracing makes object-heavy code several times slower): the seconds are then close to real.")
        parser.add_argument("--profile", action="append", default=[], help="Print where the time goes (cProfile) for the operation with this name.")

    def handle(self, *args, **options):
        from accounts.models import ROLE_EDITOR, Profile, User
        from accounts.profiles import set_user_profile
        from accounts.suite import KEY_INVESTMENTS
        from investments import bench

        self.failures = []
        self.stdout.write(f"INFO startup_rss_mb={_fmt(_rss_mb())}")
        try:
            with transaction.atomic():
                profile = Profile.objects.create(name="bench-throwaway", program=KEY_INVESTMENTS)
                user = User.objects.create_user(username="bench-throwaway", password=None, is_superuser=True)
                set_user_profile(user, profile, ROLE_EDITOR, KEY_INVESTMENTS)
                ctx = bench.BenchContext(profile=profile, user=user, seed=options["seed"], size=options["dataset_size"])
                from investments import bench_data  # noqa: F401  (registers the dataset hooks when present)

                wanted = options.get("only")
                self.profile = set(options.get("profile") or [])
                self.timing_only = options.get("timing_only")
                for name, cap, _needs_dataset, fn in bench.OPERATIONS:
                    if wanted and name not in wanted:
                        continue
                    self._run(name, cap, fn, ctx)
                raise _Rollback()
        except _Rollback:
            pass
        self.stdout.write("BENCH done")
        if self.failures:
            raise CommandError("Over budget or failed: " + ", ".join(self.failures))

    def _run(self, name, cap, fn, ctx):
        status, peak = "OK", 0.0
        queries = [0]

        def count(execute, sql, params, many, context):
            queries[0] += 1
            return execute(sql, params, many, context)

        began = time.perf_counter()
        try:
            with transaction.atomic(), connection.execute_wrapper(count):
                if getattr(self, "timing_only", False):
                    fn(ctx)
                else:
                    with assert_peak_under(_BenchCase(), cap) as box:
                        if name in getattr(self, "profile", ()):
                            self._profiled(name, fn, ctx)
                        else:
                            fn(ctx)
                    peak = box[0]
        except _PeakFail as exc:
            status = "OVER"
            peak = _parse_peak(str(exc), cap)
        except Exception:
            status = "ERROR"
            self.stderr.write(traceback.format_exc())
        if status != "OK":
            self.failures.append(name)
        self.stdout.write(
            f"BENCH {name} rss_peak_mb={_fmt(_rss_mb())} tracemalloc_peak_mb={_fmt(peak)} cap_mb={cap:.1f} seconds={time.perf_counter() - began:.2f} queries={queries[0]} status={status}"
        )


def _profiled(self, name, fn, ctx):
    """Run ``fn`` under cProfile and print the 40 most expensive calls by cumulative and by own time (slower than a plain run)."""
    import cProfile
    import io
    import pstats

    profiler = cProfile.Profile()
    profiler.runcall(fn, ctx)
    for order in ("cumulative", "tottime"):
        out = io.StringIO()
        pstats.Stats(profiler, stream=out).sort_stats(order).print_stats(40)
        self.stdout.write(f"PROFILE {name} by {order}\n{out.getvalue()}")


Command._profiled = _profiled


def _parse_peak(message, default):
    import re

    found = re.search(r"([0-9]+\.[0-9]+)\s*MB", message)
    return float(found.group(1)) if found else default
