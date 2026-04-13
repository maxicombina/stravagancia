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

echo "Starting Django..."
exec uv run python manage.py runserver 0.0.0.0:8000
