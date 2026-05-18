"""
Upload a .gpx file to Strava as if it came from Garmin Connect, to exercise
the end-to-end auto-rename flow via the webhook.

Requires the `activity:write` scope on the refresh token.

Usage:
    python manage.py upload_test_gpx ride.gpx
    python manage.py upload_test_gpx ride.gpx --activity-type ride --no-wait
    python manage.py upload_test_gpx ride.gpx --external-id custom-id-2026-05-18

After uploading, Strava processes the file (seconds to minutes) and emits the
`create` webhook. If your app is running and subscribed to the webhook, it
should:
  1. receive the create event
  2. fetch the detail + store in DB
  3. dispatch the auto-rename thread
  4. geocode + PUT with the new name
  5. receive the resulting `update` event — store only, no rename

If Strava rejects the upload as duplicate (same timestamp), shift the times
in the .gpx before retrying.
"""

import time
from pathlib import Path

import requests
from django.core.management.base import BaseCommand, CommandError

from strava_integration.utils import refresh_access_token

STRAVA_API_BASE = "https://www.strava.com/api/v3"


class Command(BaseCommand):
    help = "Upload a .gpx file to Strava to exercise the auto-rename webhook flow."

    def add_arguments(self, parser):
        parser.add_argument("gpx_path", type=str, help="Path to the .gpx file")
        parser.add_argument(
            "--activity-type",
            default="ride",
            help="Activity type (ride, run, walk, ...). Default: ride",
        )
        parser.add_argument(
            "--external-id",
            default=None,
            help="External ID for idempotency (Strava rejects duplicates).",
        )
        parser.add_argument(
            "--no-wait",
            action="store_true",
            help="Do not wait for Strava to process — upload and exit.",
        )
        parser.add_argument(
            "--wait-timeout",
            type=int,
            default=120,
            help="Max seconds to wait for the activity_id (default 120).",
        )

    def handle(self, *args, **options):
        gpx_path = Path(options["gpx_path"])
        if not gpx_path.is_file():
            raise CommandError(f"File does not exist: {gpx_path}")

        token = refresh_access_token()

        self.stdout.write(f"Uploading {gpx_path} to Strava...")
        upload_id = self._upload(token, gpx_path, options["activity_type"], options["external_id"])
        self.stdout.write(self.style.SUCCESS(f"Upload accepted. upload_id={upload_id}"))

        if options["no_wait"]:
            self.stdout.write("(--no-wait) done. Check Strava in a few seconds.")
            return

        self._poll(token, upload_id, options["wait_timeout"])

    def _upload(self, token, gpx_path: Path, activity_type: str, external_id):
        data = {"data_type": "gpx", "activity_type": activity_type}
        if external_id:
            data["external_id"] = external_id

        with gpx_path.open("rb") as fh:
            files = {"file": (gpx_path.name, fh, "application/gpx+xml")}
            r = requests.post(
                f"{STRAVA_API_BASE}/uploads",
                headers={"Authorization": f"Bearer {token}"},
                data=data,
                files=files,
                timeout=60,
            )

        if r.status_code >= 400:
            raise CommandError(f"Strava upload error {r.status_code}: {r.text}")

        body = r.json()
        if body.get("error"):
            raise CommandError(f"Strava rejected the upload: {body['error']}")
        return body["id"]

    def _poll(self, token, upload_id: int, timeout: int):
        self.stdout.write(f"Waiting for Strava to process the upload (max {timeout}s)...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(3)
            r = requests.get(
                f"{STRAVA_API_BASE}/uploads/{upload_id}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15,
            )
            r.raise_for_status()
            body = r.json()
            status = body.get("status")
            err = body.get("error")
            activity_id = body.get("activity_id")

            if err:
                raise CommandError(f"Strava upload error: {err}")
            if activity_id:
                self.stdout.write(self.style.SUCCESS(
                    f"Activity created on Strava: id={activity_id}\n"
                    f"  https://www.strava.com/activities/{activity_id}"
                ))
                self.stdout.write(
                    "The `create` webhook should now reach the server. "
                    "Check the logs (`grep 'Strava webhook event'`)."
                )
                return
            self.stdout.write(f"  ...status: {status}")

        raise CommandError(f"Timed out after {timeout}s — upload is still processing.")
