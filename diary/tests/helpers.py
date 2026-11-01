from accounts.models import Profile
from accounts.profiles import set_user_profile


def main_profile():
    """The "Main" Case Law Diary profile that the data migration creates in every database."""
    return Profile.objects.get(program="diary", name="Main", deleted_at__isnull=True)


def join_main(user, role="reader"):
    """Give ``user`` access to the "Main" profile as ``role`` (test users created after the migration have none)."""
    set_user_profile(user, main_profile(), role)
    return user
