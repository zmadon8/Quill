from django.apps import apps
from django.core.management.base import BaseCommand

from diary import subtopic_one, topic_one


class Command(BaseCommand):
    help = (
        "House Sub-topics, Items and Sections that sit directly under a Subject in that Subject's Topic called \"1\" "
        "(docs/DESIGN.md D61, D82). Migrations 0017 and 0018 did this once for the stored data; run this after a fresh "
        "Word import, which places such records exactly where the file puts them. Safe to run again."
    )

    def handle(self, *args, **options):
        found = False
        for module, stats in (("subtopics", subtopic_one.migrate_direct(apps)), ("items", topic_one.migrate_loose(apps))):
            text = (subtopic_one if module == "subtopics" else topic_one).describe(stats)
            if text:
                found = True
                self.stdout.write(self.style.SUCCESS(text))
        if not found:
            self.stdout.write("Nothing to house: every Sub-topic, Item and Section is already in a Topic.")
