"""Which source and price basis a new investment gets (plan 15.3 and 16.2). Kept apart from ``fetch`` so ``masters`` can use it
without importing the adapters."""
from investments.models import BASIS_ADJ, KIND_FOREIGN, KIND_FUND, KIND_INDEX, KIND_SHARE


def default_source(kind):
    return {KIND_SHARE: "yahoo", KIND_FOREIGN: "yahoo", KIND_INDEX: "yahoo", KIND_FUND: "amfi"}.get(kind, "manual")


def default_basis(source):
    return BASIS_ADJ if source == "yahoo" else ""
