"""``fees_payment_audit``: a read-only look at the payment data before database rules are added.

Reports memos paid more than their total (counting the TDS), negative allocation rows, and the same payment applied to the
same memo twice, plus a few things for information (see ``fees.services.payment_audit``). It changes nothing. It exits with an
error when it finds a problem a database rule would refuse, so a script can stop on it.

    python manage.py fees_payment_audit            # every live Fee Register profile
    python manage.py fees_payment_audit --profile 3
"""
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.services import payment_audit


class Command(BaseCommand):
    help = "Report overpaid memos, negative or repeated allocations and other payment oddities (read-only)."

    def add_arguments(self, parser):
        parser.add_argument("--profile", type=int, default=None, help="Only the Fee Register profile with this id.")

    def handle(self, *args, **options):
        if options["profile"] is not None:
            profile = Profile.objects.filter(pk=options["profile"], program=KEY_FEES, deleted_at__isnull=True).first()
            if profile is None:
                raise CommandError(f"No live Fee Register profile with id {options['profile']}.")
            reports = [payment_audit.audit_profile(profile)]
        else:
            reports = payment_audit.audit_all()
        for report in reports:
            for line in payment_audit.format_report(report):
                self.stdout.write(line)
            self.stdout.write("")
        blocking = sum(r.blocking for r in reports)
        if blocking:
            raise CommandError(f"{blocking} problem(s) found that a database rule would refuse. Nothing was changed.")
