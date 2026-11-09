"""The one-at-a-time lock (`fees.services.heavy`) used by every heavy Investments operation (plan 26.2 rule 4)."""
from fees.services.heavy import Busy, heavy_operation

heavy = heavy_operation

__all__ = ["Busy", "heavy", "heavy_operation"]
