"""System checks of Garage (garage-047 F10)."""
from django.core.checks import Error
from django.db import connections

from .ordering import COLLATION


def collation_check(app_configs=None, databases=None, **kwargs):
    """garage.E001: a PostgreSQL database without the Spanish ICU collation that every list and selector sorts with.

    Without it those pages fail (the database rejects the unknown collation) instead of sorting worse. Only the
    databases Django passes are read: `migrate` and `check --database …` pass theirs; `runserver` and a plain
    `check` pass none, and nothing is read.
    """
    errors = []
    for alias in databases or ():
        connection = connections[alias]
        if connection.vendor != "postgresql":
            continue
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_collation WHERE collname = %s", [COLLATION])
            found = cursor.fetchone() is not None
        if not found:
            errors.append(Error(
                f"The database '{alias}' has no collation '{COLLATION}': every Garage page that lists or offers names "
                "sorted alphabetically would fail.",
                hint="Use a PostgreSQL built with ICU (pg_collation lists the ICU collations).",
                id="garage.E001"))
    return errors
