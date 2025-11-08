# strava_integration/management/commands/detect_missing_activities.py
from django.core.management.base import BaseCommand
from strava_integration.services import detect_and_save_missing_activities

class Command(BaseCommand):
    help = "Detect missing Strava activities, store them in MissingActivity, and show a summary."

    def handle(self, *args, **options):

        try:
            response = detect_and_save_missing_activities()
        except Exception:
            self.stdout.write(self.style.ERROR("Error detecting and saveing missing activities"))
            return

        self.stdout.write(self.style.SUCCESS("✅ Missing activities detected successfully."))
        self.stdout.write(f"Total missing detected: {response['total_missing_detected']}")
        self.stdout.write(f"New missing added: {response['new_missing_added']}")
        self.stdout.write(f"Already present (unloaded): {response['already_present_unloaded']}")
        self.stdout.write(f"Already present (loaded): {response['already_present_loaded']}")
