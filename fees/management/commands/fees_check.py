"""Read-only data-integrity command (``fees_check``) for the Fee Register (R-DATA-4, design 4).

Recomputes every stored memo total from first principles via
``fees.services.integrity.run_check`` and PRINTS any mismatch. It never writes
or fixes anything (design section 4: it "returns mismatches"). It is meant as a
safety net after a restore / import and as a nightly tripwire, so the exit code
matters:

* exit 0 and a "all N memos consistent" line when nothing drifted;
* non-zero (raising ``CommandError``) naming the drifted memos when any stored
  value disagrees with its recomputed value, so a cron / script can trip on it.

Options:

* ``--profile <id>`` check one profile by id (must be a live Fee Register
  profile); default is every live Fee Register profile.

Follows the style of ``create_fees_user`` (``add_arguments`` with ``argparse``,
``BaseCommand.handle``, ``self.stdout`` / ``self.style``). It imports only the
``fees`` integrity service and never touches ``diary``.
"""
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Profile
from accounts.suite import KEY_FEES
from fees.services.integrity import run_check, summarise


class Command(BaseCommand):
    help = (
        "Recompute every memo's stored total_fees and paid amounts from first principles and report "
        "any mismatch (read-only). Exits non-zero if any mismatch is found, so it can be used as a "
        "nightly tripwire. Checks all Fee Register profiles unless --profile is given."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile",
            type=int,
            default=None,
            help="Check only the Fee Register profile with this id (default: all fees profiles).",
        )

    def handle(self, *args, **options):
        profile_id = options.get("profile")

        if profile_id is not None:
            profile = Profile.objects.filter(
                pk=profile_id, program=KEY_FEES, deleted_at__isnull=True
            ).first()
            if profile is None:
                raise CommandError(
                    f"No live Fee Register profile with id {profile_id}."
                )
            reports = [run_check(profile)]
        else:
            reports = run_check(None)

        for report in reports:
            self._print_report(report)

        summary = summarise(reports)
        if summary.ok:
            self.stdout.write(
                self.style.SUCCESS(
                    f"All {summary.memos_checked} memos consistent across "
                    f"{summary.profiles_checked} profile(s)."
                )
            )
            return

        # Non-zero exit via CommandError so a script / cron trips on it.
        raise CommandError(
            f"{summary.mismatches} mismatch(es) found across "
            f"{summary.profiles_checked} profile(s) ({summary.memos_checked} memos checked)."
        )

    def _print_report(self, report):
        """Prints one profile's result: memos checked and every mismatch line."""
        header = f"Profile {report.profile_id}: {report.memos_checked} memos checked"
        if report.ok:
            self.stdout.write(self.style.SUCCESS(f"{header}, no mismatches."))
            return
        self.stdout.write(
            self.style.ERROR(f"{header}, {len(report.mismatches)} mismatch(es):")
        )
        for m in report.mismatches:
            label = m.memo_number or f"draft memo {m.memo_id}"
            self.stdout.write(
                self.style.ERROR(
                    f"  memo {label} (id {m.memo_id}) field {m.field}: "
                    f"stored {m.stored} expected {m.expected}"
                )
            )
