# strava_integration/management/commands/detect_missing_activities.py
from django.core.management.base import BaseCommand
from django.test import RequestFactory
from strava_integration.views import detect_missing_activities
import json

class Command(BaseCommand):
    help = "Detect missing Strava activities, store them in MissingActivity, and show a summary."

    def handle(self, *args, **options):
        rf = RequestFactory()
        request = rf.get("/strava/detect_missing_activities/")

        response = detect_missing_activities(request)

        try:
            data = json.loads(response.content)
        except Exception:
            self.stdout.write(self.style.ERROR("Could not parse response JSON."))
            self.stdout.write(str(response.content))
            return

        if data.get("status") == "ok":
            self.stdout.write(self.style.SUCCESS("✅ Missing activities detected successfully."))
            self.stdout.write(f"Total missing detected: {data['total_missing_detected']}")
            self.stdout.write(f"New missing added: {data['new_missing_added']}")
            self.stdout.write(f"Already present (unloaded): {data['already_present_unloaded']}")
            self.stdout.write(f"Already present (loaded): {data['already_present_loaded']}")
        else:
            self.stdout.write(self.style.ERROR("❌ Error detecting missing activities"))
            self.stdout.write(data.get("message", "Unknown error"))
