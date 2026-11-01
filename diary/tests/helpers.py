from accounts.models import Profile


def main_profile():
    """The "Main" Case Law Diary profile that the data migration creates in every database."""
    return Profile.objects.get(program="diary", name="Main", deleted_at__isnull=True)
