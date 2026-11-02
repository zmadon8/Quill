from accounts.models import Profile
from accounts.profiles import set_user_profile


def main_profile():
    """The "Main" Case Law Diary profile that the data migration creates in every database."""
    return Profile.objects.get(program="diary", name="Main", deleted_at__isnull=True)


def join_main(user, role="reader"):
    """Give ``user`` access to the "Main" profile as ``role`` (test users created after the migration have none)."""
    set_user_profile(user, main_profile(), role)
    return user


def allow_old_shape_items(testcase):
    """Lift constraint ``item_plain_has_no_citation`` for ONE test, so it can build the pre-10d data (a plain
    Item with its own citation) that migration 0010, the backup loader and History restore must map.

    Call it first in ``setUp``. The ALTER TABLE is rolled back with the test's transaction (PostgreSQL, which
    CI uses); SQLite cannot alter a table inside the test transaction, so these tests are skipped there.
    """
    from django.db import connection

    from diary.models import Item

    if connection.vendor != "postgresql":
        testcase.skipTest("Building pre-10d data needs PostgreSQL (the constraint is dropped inside the test transaction).")
    constraint = next(c for c in Item._meta.constraints if c.name == "item_plain_has_no_citation")
    with connection.schema_editor() as editor:
        editor.remove_constraint(Item, constraint)
