"""Retry only tracked, due photo cleanup records; never list a bucket."""
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError

from garage.services.photos import retry_photo_cleanup


class Command(BaseCommand):
    help = "Retry due photo object cleanup; use --dry-run to inspect counts without storage calls."

    def add_arguments(self, parser):
        parser.add_argument("--owner", type=int, help="Optional owner ID; otherwise process due jobs for all owners.")
        parser.add_argument("--limit", type=int, default=100)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            result = retry_photo_cleanup(owner_id=options["owner"], limit=options["limit"], dry_run=options["dry_run"])
        except (ValidationError, DatabaseError):
            raise CommandError("Photo cleanup could not run. Check server configuration and database availability.") from None
        label = "dry-run" if options["dry_run"] else "cleanup"
        self.stdout.write(f"{label}: scanned={result.scanned} deleted={result.deleted} failed={result.failed} skipped={result.skipped} deferred={result.deferred}")
