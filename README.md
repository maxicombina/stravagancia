# What's this about
A project to learn Python+Django by creating a small web app to track my Strava Ride activities.

# Why
On one hand, I am learning Python+Django.

On the other hand, I want to keep track of my personal Strava Ride activities and be able to visualize data in ways which are not always present in Strava nor Garmin Connect.

So, why not?
It's a good excuse to learn something new and useful, while being able to view my Ride data in the way I want.

# What does it do?
- Loads one Strava athlete and syncs all Ride activities
- Real-time sync via Strava webhook (`create` / `update` / `delete`)
- Auto-renames generic activity names (e.g. "Morning Ride" → "Cornellà - [Molins] - Turó d'en Pisca - Cornellà ~8km spacing") using Overpass (peaks/saddles) + Nominatim (municipalities) reverse-geocoding
- Public dashboard with paginated activity list and embedded Grafana charts
- Detects missing activities and provides one-click sync to backfill them
- Django admin with custom bulk actions: re-trigger auto-rename, force auto-rename
- Optional Metabase/Grafana containers via `docker-compose.yml` for ad-hoc visualisations
- Test suite with 90+ pytest tests (mocking external HTTP)

# How does it look like?
![Example Dashboard](assets/dashboard_preview.png)

> Note: screenshot is from an earlier version of the dashboard — TODO refresh.

# Known issues and limitations
- Only one user supported.
- Render free tier sleeps after 15 min idle → the first webhook after sleep may miss; Strava retries automatically over the following hours.
- Geocoding (Nominatim) can be non-deterministic on administrative boundary coordinates — a point on a municipal border may resolve to one side or the other at different times. Rare; the force auto-rename admin action can be used to re-roll if needed.

# Next steps
- Improve visualisations of the data (e.g., total distance per month, average speed, calories per month).

# How to use this project
## On Strava
- Enable the Strava API. As of this writing, go to https://www.strava.com/settings/api and create an app.

## Locally
- Make sure you have Python and uv installed (https://github.com/astral-sh/uv))
  - And docker for Metabase
- Clone this repo
- `cd` into the project folder and run the following commands:
  - `uv venv --seed`
  - `source .venv/bin/activate`
  - `uv sync`
- Initialize the environment variables. Create a `.env` file in the project root with the following variables:
  - `STRAVA_ACCESS_TOKEN=your_strava_access_token`
  - `STRAVA_CLIENT_ID=your_strava_client_id`
  - `STRAVA_CLIENT_SECRET=your_strava_client_secret`
  - `STRAVA_REFRESH_TOKEN=your_strava_refresh_token`
  - `DB_NAME`=stravagancia 
  - `DB_USER`=strava 
  - `DB_PASSWORD`=strava 
  - `DB_HOST`=localhost 
  - `DB_PORT`=5432
- Initialize the database and load data:
  - `docker compose up -d postgres`
  - `python manage.py migrate`
  - `python manage.py createsuperuser`
  - `python test_strava_connection.py` (to verify Strava API access)
  - `python manage.py load_athlete`
  - `python manage.py detect_missing_activities`
  - `python manage.py load_missing_activities`: may take a while depending on how many activities you have
- Run tests: `pytest` (uses `pytest-django`)
- To exercise the webhook end-to-end with a real Strava upload (requires `activity:write` scope on the refresh token):
  - `python manage.py upload_test_gpx path/to/ride.gpx`
- Optionally: Run metabase using docker-compose:
  - `docker-compose up` (Will launch Metabase on port 3000)
- Optionally: run the Django development server:
  - `python manage.py runserver`
  - Access the admin interface at http://localhost:8000/admin using the superuser credentials created before.
  - Some basic URLs are already wired up in strava_integration/urls.py for exploration.

Auth in metabase:
- email: admin@admin.com  
- password: django-strava-01

## In production (Render + Neon)

This project runs on Render's free tier (Docker service) with a Neon Postgres database. The deployed app is live at https://stravagancia.onrender.com.

- The service container builds from `Dockerfile` and runs `entrypoint.sh` (migrate, create superuser, collectstatic, gunicorn).
- Auto-deploys on `git push origin main`.
- Env vars set on Render:
  - `STRAVA_REFRESH_TOKEN` (only the refresh token — access tokens are minted on each call by `utils.refresh_access_token`)
  - `STRAVA_CLIENT_ID`, `STRAVA_CLIENT_SECRET`
  - `STRAVA_WEBHOOK_VERIFY_TOKEN`
  - `DATABASE_URL` (Neon connection string)
  - `SECRET_KEY`, `ALLOWED_HOSTS`
  - Optional: `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL` (used once by `entrypoint.sh` to create the admin user on first boot).


- Unfold: theme para el admin
