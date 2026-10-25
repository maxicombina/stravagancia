"""Reconstruct only an explicitly selected active owner's own usage facts."""
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from garage.services.usage import rebuild_usage


class Command(BaseCommand):
    help = "Rebuild an owner's item usage for an optional UTC/offset interval."

    def add_arguments(self, parser):
        parser.add_argument("--owner", required=True, type=int, help="Explicit active authentication user ID")
        parser.add_argument("--from", dest="started_from", help="Inclusive ISO instant with explicit UTC/offset")
        parser.add_argument("--to", dest="started_to", help="Exclusive ISO instant with explicit UTC/offset")
        parser.add_argument("--dry-run", action="store_true", help="Report deltas without writing any data")

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options["owner"], is_active=True).first()
        if actor is None:
            raise CommandError("Choose an existing active owner.")
        dates = {}
        for field in ("started_from", "started_to"):
            if options[field] is not None:
                try:
                    dates[field] = datetime.fromisoformat(options[field])
                except (ValueError, TypeError):
                    raise CommandError("Use ISO instants with an explicit time zone.") from None
        try:
            result = rebuild_usage(actor, **dates, dry_run=options["dry_run"])
        except PermissionDenied:
            raise CommandError("Choose an existing active owner.") from None
        except ValidationError as error:
            raise CommandError("Invalid reconstruction request: " + "; ".join(error.messages)) from None
        mode = "dry-run" if result.dry_run else "rebuilt"
        self.stdout.write(f"{mode}: rides={len(result.plans)} created={result.created} updated={result.updated} deleted={result.deleted} unchanged={result.unchanged}")
