"""Database rule builders shared by the models and the migration.

Kept free of model imports so the initial migration can use the very same
objects as the models (so ``makemigrations --check`` always sees no change).
"""
from django.db.models import Q


def exactly_one(columns):
    """A check rule: exactly one of ``columns`` is filled and all the others are empty."""
    options = []
    for chosen in columns:
        parts = [(f"{column}__isnull", column != chosen) for column in columns]
        options.append(Q(*parts))
    rule = options[0]
    for option in options[1:]:
        rule = rule | option
    return rule


def not_blank(column):
    """A check rule: ``column`` is not an empty string."""
    return ~Q(**{column: ""})

