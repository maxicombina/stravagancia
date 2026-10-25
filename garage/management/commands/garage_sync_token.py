"""Print a fresh GARAGE_SYNC_TOKEN once (garage-030 phase 4); nothing is written anywhere."""
import secrets

from django.core.management.base import BaseCommand

TOKEN_BYTES = 48  # 64 URL-safe characters, well above the 32 the endpoint requires


class Command(BaseCommand):
    help = ("Print a new random token for GARAGE_SYNC_TOKEN (Render) and the Worker secret SYNC_TOKEN. "
            "It is shown once and stored nowhere: no .env nor any other file is written.")

    def handle(self, *args, **options):
        self.stdout.write(secrets.token_urlsafe(TOKEN_BYTES))
