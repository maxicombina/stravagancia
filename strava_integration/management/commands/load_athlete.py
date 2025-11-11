from django.core.management.base import BaseCommand
from django.test import RequestFactory
from strava_integration.services import fetch_and_store_athlete

class Command(BaseCommand):
    help = "Fetch the current authenticated Strava athlete and stores it in the DB. Can be an update."

    def handle(self, *args, **options):

        try:
            athlete, created = fetch_and_store_athlete()
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error loading athlete: {e}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Response: created: {created}, athlete: {athlete}"))
        self.stdout.write(self.style.SUCCESS("✅ Athlete loaded successfully."))
