"""Read-only report of every Item that sits beneath another Item (the old "Nested Item" data).

Safe to run on the OLD running version before the update: it only reads, with plain SQL, the columns
``id, profile_id, kind, deleted_at, parent_item_id, text_plain``. If the table has no ``parent_item_id`` column
(the update has already removed it) it says so. It changes nothing.

    python manage.py nested_report
"""
from django.core.management.base import BaseCommand
from django.db import connection

from diary.nested_conversion import conversion_order


def handling(row, parent, children_of):
    """One line saying what the Nested Item conversion does with this row (see docs/DESIGN.md, round 11 hotfix)."""
    if parent is None:
        return "parent row is missing: the Item is detached and keeps its state"
    live, parent_live = row["deleted_at"] is None, parent["deleted_at"] is None
    if live and parent_live:
        return "folded into the parent (its text becomes a citation comment); the Item itself goes to Trash"
    if live:
        return "folded into the trashed parent; the Item waits in Trash"
    return "stays in Trash, detached from the parent so it can be restored on its own"


class Command(BaseCommand):
    help = "Print every Item that sits beneath another Item and how the update will treat it. Changes nothing."

    def handle(self, *args, **options):
        table = "diary_item"
        with connection.cursor() as cursor:
            columns = {c.name for c in connection.introspection.get_table_description(cursor, table)}
            if "parent_item_id" not in columns:
                self.stdout.write("The Item table has no parent_item column: no Item can sit beneath another Item.")
                return
            cursor.execute(
                f"SELECT id, profile_id, kind, deleted_at, parent_item_id, text_plain FROM {table}"
            )
            rows = {
                r[0]: {"id": r[0], "profile": r[1], "kind": r[2], "deleted_at": r[3], "parent": r[4], "text": r[5] or ""}
                for r in cursor.fetchall()
            }
        parent_of = {pk: r["parent"] for pk, r in rows.items() if r["parent"] is not None}
        children_of = {}
        for pk, parent in parent_of.items():
            children_of.setdefault(parent, []).append(pk)
        nested = [pk for pk, r in rows.items() if r["kind"] == "nested"]
        self.stdout.write(
            f"{len(rows)} Items in all; {len(nested)} Nested Items; {len(parent_of)} Items sit beneath another Item."
        )

        def depth(pk):
            seen, count = {pk}, 0
            while rows[pk]["parent"] in rows:
                pk = rows[pk]["parent"]
                if pk in seen:
                    return -1
                seen.add(pk)
                count += 1
            return count

        odd = 0
        for pk in sorted(parent_of):
            row = rows[pk]
            parent = rows.get(row["parent"])
            note = "" if parent and parent["kind"] == "nested" else "  <-- parent is not a Nested Item"
            odd += bool(note)
            self.stdout.write(
                f"Item {pk} (profile {row['profile']}, {'live' if row['deleted_at'] is None else 'in Trash'}, "
                f"depth {depth(pk)}) beneath Item {row['parent']} "
                f"({parent['kind'] if parent else 'missing'}, "
                f"{'live' if parent and parent['deleted_at'] is None else 'in Trash'}): "
                f"{row['text'][:60]!r}{note}\n    -> {handling(row, parent, children_of)}"
            )
        self.stdout.write(f"Conversion order (deepest first): {conversion_order(parent_of, nested)}")
        self.stdout.write(f"{odd} Item(s) sit beneath a parent that is not a Nested Item.")
