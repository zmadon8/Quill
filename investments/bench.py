"""Operations measured by ``investments_memory_bench`` (plan 26.2 rule 9).

Each phase registers the operations it adds with ``@operation(name, cap_mb)``. An operation is a function
``fn(ctx)`` where ``ctx`` is a ``BenchContext`` holding a throwaway profile and user (everything runs inside a transaction
that the command rolls back). The cap is the peak of Python allocations (``tracemalloc``), the figure plan 26.1 is written
against. Caps below are the plan's estimates; the real numbers replace them in docs/INVESTMENTS_RAM.md.
"""
from dataclasses import dataclass, field

OPERATIONS = []


@dataclass
class BenchContext:
    profile: object
    user: object
    seed: int = 0
    size: str = "planning"
    extra: dict = field(default_factory=dict)


def operation(name, cap_mb, needs_dataset=False):
    """Register ``fn`` as a benchmark operation."""

    def decorator(fn):
        OPERATIONS.append((name, cap_mb, needs_dataset, fn))
        return fn

    return decorator


@operation("money_format", 3.0)
def money_format(ctx):
    """Format 10,000 amounts in both modes (what a big table does on the server)."""
    from investments.money_auto import AUTO, FULL, format_rupees

    for i in range(10000):
        value = (i * 7919) % 99999999
        format_rupees(value, mode=AUTO)
        format_rupees(value, mode=FULL, signed=True)


@operation("shell_pages", 10.0)
def shell_pages(ctx):
    """Render every page of the menu once (ordinary page cost, plan 26.1 "Ordinary page: 3 to 10 MB")."""
    from django.test import RequestFactory
    from django.urls import resolve

    from investments import pages

    from django.test import override_settings

    plain_static = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    factory = RequestFactory()
    # The bench runs without collectstatic, so the manifest storage would fail on the first {% static %}.
    with override_settings(STORAGES=plain_static):
        for page in pages.PAGES:
            path = "/investments/" + page.path
            request = factory.get(path)
            request.user = ctx.user
            request.resolver_match = resolve(path)
            response = request.resolver_match.func(request)
            if hasattr(response, "render"):
                response.render()
            if response.status_code != 200:
                raise RuntimeError(f"{path} answered {response.status_code}")
