# strava_integration/management/commands/detect_missing_activities.py
from django.core.management.base import BaseCommand
from strava_integration.services import detect_and_save_missing_activities

class Command(BaseCommand):
    help = "Detect missing Strava activities, store them in MissingActivity, and show a summary."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Only detect missing activities without saving them.'
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.NOTICE("🧪 Running in dry-run mode — no data will be saved."))

        try:
            response = detect_and_save_missing_activities(dry_run=dry_run)
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error detecting and saving missing activities: {e}"))
            return

        mode = "🔍 Detection only (no save)" if dry_run else "💾 Detection and save"
        self.stdout.write(self.style.SUCCESS(f"{mode} completed successfully."))
        self.stdout.write(f"Total missing detected: {response['total_missing_detected']}")
        self.stdout.write(f"New missing added: {response['new_missing_added']}")
        self.stdout.write(f"Already present (unloaded): {response['already_present_unloaded']}")
        self.stdout.write(f"Already present (loaded): {response['already_present_loaded']}")
