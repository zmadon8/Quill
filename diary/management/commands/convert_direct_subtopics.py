from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Profile
from accounts.suite import KEY_DIARY
from backups import services as backup_services
from diary import topic_one
from diary.services import direct_subtopics as flatten


class Command(BaseCommand):
    help = (
        "Turn every Sub-topic that sits directly under a Subject (the Other Subjects, from the Word import) into a Topic "
        "of that Subject, so every Subject is Subject > Topic > Sub-topic (docs/DESIGN.md D81). By default only SHOWS what "
        "would change. Use --convert to do it: a backup is taken first, the change is all or nothing, the old Sub-topics "
        "go to the Trash, and loose Items are then housed in Topic \"1\". Safe to run again."
    )

    def add_arguments(self, parser):
        parser.add_argument("--profile", help="Name of one Case Law Diary profile (default: every profile).")
        parser.add_argument("--convert", action="store_true", help="Really convert (after looking at the dry run).")
        parser.add_argument("--user", help="Username recorded in the history (default: the first active Admin).")

    def handle(self, *args, **options):
        profiles = Profile.objects.filter(program=KEY_DIARY, deleted_at__isnull=True).order_by("name")
        if options["profile"]:
            profiles = profiles.filter(name__iexact=options["profile"].strip())
            if not profiles.exists():
                raise CommandError(f"There is no profile called '{options['profile']}'.")
        if not options["convert"]:
            self.dry_run(profiles)
            return
        User = get_user_model()
        if options["user"]:
            user = User.objects.filter(username__iexact=options["user"], is_active=True).first()
        else:
            user = User.objects.filter(is_superuser=True, is_active=True).order_by("pk").first()
        if user is None:
            raise CommandError("No active user found to record in the history. Use --user USERNAME.")
        if not any(flatten.direct_subtopics(p) for p in profiles):
            self.stdout.write("Nothing to convert: no Sub-topic sits directly under a Subject.")
        else:
            try:
                backup = backup_services.create_backup("manual", user)
            except Exception as exc:
                raise CommandError(f"The safety backup FAILED, so nothing was changed. ({exc})")
            self.stdout.write(f"Safety backup taken: {backup.filename}")
            for profile in profiles:
                try:
                    result = flatten.convert(profile, user)
                except flatten.ConversionMismatch as exc:
                    raise CommandError(f"Profile '{profile.name}': stopped and rolled back, nothing changed there. {exc}")
                self.stdout.write(
                    self.style.SUCCESS(f"Profile '{profile.name}': {result['converted']} Sub-topic(s) are now Topics.")
                )
        # Items that sat loose under such a Subject can now be housed in Topic "1" like everywhere else (D61).
        stats = topic_one.migrate_loose(apps)
        text = topic_one.describe(stats)
        if text:
            self.stdout.write(self.style.SUCCESS(text))

    def dry_run(self, profiles):
        total = 0
        for profile in profiles:
            rows = flatten.plan(profile)
            if not rows:
                continue
            self.stdout.write(f"Profile '{profile.name}':")
            for subject, subs in rows:
                self.stdout.write(f"  {subject}")
                for name, items in subs:
                    total += 1
                    self.stdout.write(f"    Sub-topic '{name}' ({items} Item(s)) would become a Topic")
        if not total:
            self.stdout.write("Nothing to convert: no Sub-topic sits directly under a Subject.")
            return
        self.stdout.write(
            f"\n{total} Sub-topic(s) would become Topics. Their Items, Sections and Notes move with them, in the same order; "
            "links from other Notes follow; each old Sub-topic goes to the Trash (and stays in History). Topic names show as "
            "A, B, C... (the Topic number format) where they showed as 1, 2, 3... (the Sub-topic format). Nothing was changed. "
            "Run again with --convert to do it (a backup is taken first)."
        )
