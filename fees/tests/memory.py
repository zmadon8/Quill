"""Shared memory-gate helper for the Fee Register (RAM budget section 8, R-NFR-7).

``assert_peak_under(testcase, mb)`` is the single context manager every memory-tagged fee test and
the ``fees_memory_bench`` command (T1.6) use to assert that the peak Python allocations inside a block
stay under a cap. It is stdlib-only (``tracemalloc``, optionally ``resource``) so it imports without
touching the Django app registry and carries no module-level mutable state.

``tracemalloc`` counts Python allocations, which is where nearly all the growth comes from; it
under-counts C extensions a little, so the thresholds in the RAM budget carry about a 30 percent
margin (section 8). On failure the peak and the ten largest allocation sites are shown, and where it is
available the process ``ru_maxrss`` high-water mark is recorded for information.
"""
from contextlib import contextmanager

try:  # ``resource`` is POSIX-only; it is informational, so missing is fine (e.g. on Windows).
    import resource
except ImportError:  # pragma: no cover - platform dependent
    resource = None

import tracemalloc

_ONE_MB = 1024 * 1024


def _max_rss_mb():
    """The process peak RSS in MB from ``getrusage`` where available, else ``None``.

    ``ru_maxrss`` is kilobytes on Linux and bytes on macOS; this returns the Linux reading (kilobytes)
    which is what CI measures. It is only ever shown for information, never asserted on.
    """
    if resource is None:  # pragma: no cover - platform dependent
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


@contextmanager
def assert_peak_under(testcase, mb):
    """Assert the peak Python allocations inside the block stay under ``mb`` megabytes.

    Starts ``tracemalloc``, resets the peak, runs the block, then reads ``get_traced_memory`` and takes
    a snapshot before stopping. If the peak is over the cap the test fails with the peak and the ten
    largest allocation sites. The measured peak in MB is yielded as a one-element list so a caller that
    wants it can read ``peak_box[0]`` after the block.
    """
    peak_box = [0.0]
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        yield peak_box
        _current, peak = tracemalloc.get_traced_memory()
        snapshot = tracemalloc.take_snapshot()
    finally:
        tracemalloc.stop()
    peak_box[0] = peak / _ONE_MB
    limit = mb * _ONE_MB
    if peak > limit:
        top = snapshot.statistics("lineno")[:10]
        report = "\n".join(str(line) for line in top)
        rss = _max_rss_mb()
        rss_note = f"\nprocess peak RSS about {rss:.0f} MB." if rss is not None else ""
        testcase.fail(
            f"peak {peak / _ONE_MB:.1f} MB exceeded the {mb} MB cap.{rss_note}\n"
            f"Top allocations:\n{report}"
        )
