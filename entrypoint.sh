#!/bin/sh
set -e

echo "Running migrations..."
uv run python manage.py migrate --noinput

echo "Starting Django..."
exec uv run python manage.py runserver 0.0.0.0:8000
