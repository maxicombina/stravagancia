from django.core.management.base import BaseCommand
from strava_integration.services import get_missing_ride_activity_ids

class Command(BaseCommand):
    help = "Detects Strava Ride activities not yet stored in the database"

    def handle(self, *args, **options):
        missing = get_missing_ride_activity_ids()["missing_ids"]
        if missing:
            self.stdout.write(f"Found {len(missing)} missing activities:")
            for mid in missing:
                self.stdout.write(str(mid))
        else:
            self.stdout.write("All activities are present in the database.")
