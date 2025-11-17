import json
import time
from django.core.management.base import BaseCommand
from django.test import RequestFactory
from strava_integration.models import MissingActivity
from strava_integration.services import fetch_activity_detail, store_activity_from_strava_data

class Command(BaseCommand):
    help = "Load all missing Strava activities into the database (only those not marked as loaded)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delay",
            type=int,
            default=0,
            help="Delay (in seconds) between loading activities to avoid hitting Strava API rate limits."
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Optional: limit number of missing activities to load."
        )

    def handle(self, *args, **options):
        delay = options["delay"]
        limit = options["limit"]

        # Get missing activities not yet loaded
        queryset = MissingActivity.objects.filter(loaded=False).order_by("strava_id")
        total_to_load = queryset.count()

        if limit:
            queryset = queryset[:limit]

        # If loading 100 or more activities, apply delay as API rate limit is currently set to 100 every 15 minutes
        auto_apply_delay = len(queryset) >= 100
        if auto_apply_delay and delay < 9:
            delay = delay + 9
            self.stdout.write(
                self.style.NOTICE("⚠️ 100 or more activities. Will apply extra delay between requests to avoid rate limits."))

        if total_to_load == 0:
            self.stdout.write(self.style.WARNING("No missing activities to load."))
            return

        self.stdout.write(f"Found {total_to_load} missing activities to load.")
        if limit:
            self.stdout.write(f"Limiting to first {limit} activities.")

        rf = RequestFactory()
        loaded_count = 0

        total_to_load = queryset.count()
        for idx, missing in enumerate(queryset, start=1):
            activity_id = missing.strava_id
            self.stdout.write(f"▶ Loading activity {activity_id} - {idx}/{total_to_load} ...")

            try:

                data = fetch_activity_detail(activity_id)
                activity, created = store_activity_from_strava_data(data)

                # Mark as loaded
                missing.loaded = True
                missing.save()
                loaded_count += 1
                self.stdout.write(self.style.SUCCESS(f"Activity {activity} loaded successfully."))

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Error loading {activity_id}: {e}"))

            if delay > 0 and idx < len(queryset):
                # Wait before next call
                time.sleep(delay)

        self.stdout.write(self.style.SUCCESS(f"\nDone! {loaded_count} of {total_to_load} missing activities loaded."))
