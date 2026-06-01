#!/bin/sh
set -e

echo "Running migrations..."
uv run python manage.py migrate --noinput

echo "Creating superuser if it doesn't exist..."
uv run python manage.py shell -c "
from django.contrib.auth.models import User
import os
username = os.environ.get('DJANGO_SUPERUSER_USERNAME', 'admin')
password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', 'admin')
email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '')
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username, email, password)
    print(f'Superuser {username!r} created.')
else:
    print(f'Superuser {username!r} already exists, skipping.')
"

echo "Collecting static files..."
uv run python manage.py collectstatic --noinput

echo "Starting server..."
# --timeout 60: the admin auto-rename action runs the geocoding pipeline
# synchronously (Overpass + Nominatim, several seconds per route point), which
# can exceed gunicorn's default 30s and kill the worker. 60s covers typical
# routes (~17s observed for a 25km/3-point ride). Future option if this proves
# too tight on long routes: offload the admin action to a daemon thread like the
# webhook does (_safe_auto_rename), returning immediately instead of blocking a
# worker — at the cost of losing the inline result message in the admin.
exec uv run gunicorn strava_app.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 60
