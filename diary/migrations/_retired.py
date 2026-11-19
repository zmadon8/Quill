"""Shared by the data migrations whose conversion code has been retired (diary 0010, 0015, 0017, 0018 and 0021).

Those moves were made once, long ago, on the databases that needed them, and every live database is far past them. The code that
did them was removed. A database that is still before such a migration AND holds rows would need that code, so it is refused
here instead of being skipped silently. An empty database (a new install, the tests) has nothing to move.
"""


def refuse_old_data(apps, *model_names):
    for name in model_names:
        if apps.get_model("diary", name).objects.exists():
            raise RuntimeError(
                "This database is older than this release supports and holds diary data that needs a conversion step that was "
                "retired. Update it with an earlier release first, or restore a recent backup into a new database."
            )
