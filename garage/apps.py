from django.apps import AppConfig


class GarageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "garage"

    def ready(self):
        from django.core.checks import Tags, register

        from .checks import collation_check
        # garage-047 F10: the collation the lists sort with, checked by `migrate` and `check --database default`.
        register(collation_check, Tags.database)
