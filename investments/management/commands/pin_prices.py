"""Pin the prices that reports depend on (plan 15.4 step 3, 17.2): index values on every transaction date and the prices of what was
held on every 31 March. Run nightly after `fetch_prices` and before the backup and any pruning. A pin is made from stored prices only;
anything that cannot be made yet is reported and tried again tomorrow. Always exits 0 unless the step itself breaks."""
from django.core.management.base import BaseCommand

from investments.models import PriceMaintenanceLog
from investments.services import pins


class Command(BaseCommand):
    help = __doc__.split("\n\n")[0]

    def handle(self, *args, **options):
        result = pins.pin_all()
        PriceMaintenanceLog.objects.create(kind="pin", ok=True, counts={"made": result["made"], "already": result["already"],
                                                                      "missing": len(result["missing"]), "approximate": result["approximate"]},
                                           message=f"{result['made']} pinned, {len(result['missing'])} could not be made yet")
        self.stdout.write(f"pin_prices: {result['made']} made, {result['already']} already there, {len(result['missing'])} not possible yet, "
                          f"{result['approximate']} approximate")
        for name, day, reason in result["missing"][:20]:
            self.stdout.write(f"  - {name} {day} ({reason})")
