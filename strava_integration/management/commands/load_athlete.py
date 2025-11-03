from django.core.management.base import BaseCommand
from django.test import RequestFactory
from strava_integration.views import load_athlete

class Command(BaseCommand):
    help = "Fetch the current authenticated Strava athlete via the same view used in the web UI."

    def handle(self, *args, **options):
        rf = RequestFactory()
        request = rf.get("/strava/load-athlete/")
        response = load_athlete(request)

        self.stdout.write(self.style.SUCCESS(f"Response: {response.content.decode()}"))
        self.stdout.write(self.style.SUCCESS("✅ Athlete loaded successfully."))
