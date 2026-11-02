from django.apps import apps
from django.core.management.base import BaseCommand

from diary import topic_one


class Command(BaseCommand):
    help = (
        "House Items and Sections that sit directly under a Subject in that Subject's Topic called \"1\" "
        "(docs/DESIGN.md D61). Migration 0017 did this once for the stored data; run this after a fresh Word import, "
        "which places such Items exactly where the file puts them. Safe to run again."
    )

    def handle(self, *args, **options):
        stats = topic_one.migrate_loose(apps)
        text = topic_one.describe(stats)
        self.stdout.write(self.style.SUCCESS(text) if text else "Nothing to house: every Item is already in a Topic.")
        if stats["left_under_subjects_with_subtopics"]:
            self.stdout.write(
                f"{stats['left_under_subjects_with_subtopics']} Item(s)/Section(s) stay directly under Subjects that "
                "hold Sub-topics (a Subject holds Topics or Sub-topics, not both)."
            )
