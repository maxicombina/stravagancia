"""Run the daily Strava sync once (garage-030 phase 4), as POST /garage/strava/sync-all/ does, and print its JSON."""
import json

from django.core.management.base import BaseCommand

from garage.services.strava_sync import sync_all


class Command(BaseCommand):
    help = ("Run one bounded daily Strava sync (sync_all: purge of old hints, the configured owner's week, absence "
            "hints, pending hints and the 30-day purge of a revoked account) and print the endpoint's JSON.")

    def handle(self, *args, **options):
        self.stdout.write(json.dumps(sync_all().as_json()))
