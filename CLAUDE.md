# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Stravagancia** is a Django web application that syncs Strava cycling activities to a local database (PostgreSQL) for personal data analysis and visualization. It demonstrates token refresh mechanisms, webhook handling, activity detection, and batch synchronization with an external API.

**Key Features:**
- OAuth token management with automatic refresh
- Strava API integration for fetching athlete info and activities
- Detection and sync of missing activities
- Webhook endpoint to receive real-time activity updates from Strava
- Django admin interface for data management
- Visualization dashboards via Grafana and Metabase

## Setup & Dependencies

The project uses **uv** as the Python package manager (https://github.com/astral-sh/uv) and **pytest** for testing.

**Installation:**
```bash
uv venv --seed
source .venv/bin/activate
uv sync
```

**Database Setup (local dev with Docker):**
```bash
docker compose up -d postgres
python manage.py migrate
python manage.py createsuperuser
```

**Environment Variables** (in `.env`):
```
STRAVA_ACCESS_TOKEN=...
STRAVA_CLIENT_ID=...
STRAVA_CLIENT_SECRET=...
STRAVA_REFRESH_TOKEN=...
STRAVA_WEBHOOK_VERIFY_TOKEN=...  # for webhook verification
DB_NAME=stravagancia
DB_USER=strava
DB_PASSWORD=strava
DB_HOST=localhost
DB_PORT=5432
DEBUG=true  # for local development
```

## Running Tests

Tests are configured in `pyproject.toml` using pytest with `pytest-django`:

```bash
# Run all tests
pytest

# Run a single test file
pytest strava_integration/tests.py

# Run a specific test
pytest strava_integration/tests.py::test_athlete_str

# Run with verbose output
pytest -v

# Run with coverage
pytest --cov=strava_integration
```

**Test Fixtures** (in `conftest.py`):
- `athlete`: Creates a test Athlete instance
- `activity`: Creates a test Activity instance
- `strava_activity_payload`: Returns mock Strava API response data

## Running the Dev Server

```bash
# Start Django development server
python manage.py runserver

# Access the app
# - Admin interface: http://localhost:8000/admin
# - Athlete test page: http://localhost:8000/archive/strava/test/
# - Dashboard: http://localhost:8000/archive/strava/dashboard/
# - Activities list: http://localhost:8000/activities/
```

## Common Management Commands

These are custom Django management commands in `strava_integration/management/commands/`:

```bash
# Fetch and store the authenticated athlete from Strava
python manage.py load_athlete

# Detect missing activities in Strava (not yet in local DB)
python manage.py detect_missing_activities
# With dry-run (detect only, don't save):
python manage.py detect_missing_activities --dry-run

# Load all missing activities from Strava into the database
# This respects API rate limits (100 requests per 15 minutes)
python manage.py load_missing_activities
# With delay between requests (in seconds):
python manage.py load_missing_activities --delay 10
# With limit on how many to load:
python manage.py load_missing_activities --limit 50
```

## Architecture & Code Organization

### Django Project Structure
- `strava_app/`: Main Django project configuration
  - `settings.py`: Database config (supports both `DATABASE_URL` and individual `DB_*` vars), installed apps, middleware
  - `urls.py`: Root URL configuration; routes to strava_integration app
  - `wsgi.py`, `asgi.py`: WSGI/ASGI entry points (gunicorn uses wsgi)

- `strava_integration/`: Main Django app
  - `models.py`: Three core models: **Athlete**, **Activity**, **MissingActivity**
  - `services.py`: API calls and business logic
  - `views.py`: HTTP views for API and webhook endpoints
  - `admin.py`: Django admin customizations
  - `management/commands/`: Custom management commands
  - `urls.py`: URL patterns for API endpoints (`/archive/strava/*`)
  - `ui_urls.py`: URL patterns for UI pages
  - `utils.py`: Token refresh logic

### Key Data Models

**Athlete** (`models.py`):
- Represents a Strava athlete with `strava_id` (unique)
- Stores: name, username, location, profile URL
- One Athlete can have many Activities

**Activity** (`models.py`):
- Represents a Strava activity with `strava_id` (unique)
- Stores: name, distance, time, elevation, type, calories, heart rate, timestamps
- Ordered by `-start_date` (newest first)
- Properties: `activity_url` (link to Strava), `distance_km` (converted from meters)

**MissingActivity** (`models.py`):
- Temporary tracking of activities that exist in Strava but not in local DB
- Fields: `strava_id` (unique), `start_date_local`, `loaded` (boolean)
- Once loaded into Activity, the `loaded` flag is set to True

### Key Services & API Integration

**Token Management** (`utils.py`):
- `refresh_access_token()`: Exchanges refresh token for new access token
- Persists new tokens back to `.env` for local dev (in production, use environment secrets)
- Called before every Strava API request

**Strava API Integration** (`services.py`):
- `fetch_and_store_athlete()`: Gets /athlete endpoint and stores/updates Athlete model
- `get_activities(per_page=50, after=0)`: Paginated fetch of athlete's activities
- `fetch_activity_detail(activity_id)`: Fetch single activity by ID
- `store_activity_from_strava_data(data)`: Parse Strava JSON and create/update Activity model
- `get_missing_ride_activities()`: Compare Strava vs local DB to find missing Ride-type activities
- `detect_and_save_missing_activities(dry_run=False)`: Detect and optionally persist MissingActivity records

### Activity Sync Workflow

1. **Initial Load**: `python manage.py load_athlete` → stores Athlete data
2. **Detect Missing**: `python manage.py detect_missing_activities` → finds activities in Strava not in local DB, saves as MissingActivity
3. **Batch Sync**: `python manage.py load_missing_activities` → fetches each MissingActivity detail from Strava, stores as Activity, marks `loaded=True`
4. **Real-time Updates**: Strava webhook endpoint (`/archive/strava/webhook/strava/`) receives create/update/delete events and syncs immediately

### Webhook Implementation

**Endpoint**: `POST /archive/strava/webhook/strava/` (in `views.py`)

**Verification Flow**:
1. Strava sends GET request with `hub.challenge` parameter
2. Endpoint verifies `hub.verify_token` matches `STRAVA_WEBHOOK_VERIFY_TOKEN` env var
3. Returns `{"hub.challenge": challenge}` to confirm subscription

**Event Processing**:
- `object_type`: "activity" or "athlete"
- `aspect_type`: "create", "update", or "delete"
- For activity events: fetches from Strava API and updates local Activity, or deletes if `aspect_type="delete"`
- Returns 200 within 2 seconds (Strava requirement)

### URL Routing

**API Endpoints** (`strava_integration/urls.py`):
- `GET /archive/strava/test/` → Show athlete JSON (test endpoint)
- `GET /archive/strava/athlete/` → Display stored athlete info
- `GET /archive/strava/activities_strava/` → Show Ride activities from Strava API
- `POST /archive/strava/activities/load/<int:activity_id>/` → Fetch and store single activity
- `GET /archive/strava/dashboard/` → Dashboard page with sync controls
- `GET /archive/strava/detect_missing_activities/` → Trigger missing activity detection
- `GET /archive/strava/load-athlete/` → Trigger athlete load (JSON response)
- `GET /archive/strava/missing_activities/` → List missing activities (JSON)
- `GET /archive/strava/missing/` → Missing activities list view (HTML)
- `GET /archive/strava/activities/` → Activities list view (HTML)
- `POST /archive/strava/webhook/strava/` → Webhook endpoint (GET for verification, POST for events)

## Docker & Deployment

**Local Development with Docker**:
```bash
# Start all services (Django, Postgres, Grafana, Metabase)
docker compose up

# Start only Postgres
docker compose up -d postgres

# View logs
docker compose logs -f django
```

**Docker Compose Services**:
- `postgres`: PostgreSQL 16 database (port 5432)
- `django`: Django app container (port 8000) — runs `entrypoint.sh` which migrates, creates superuser, collects static files, then starts gunicorn
- `grafana`: Grafana dashboards (port 3001) — queries Postgres directly
- `metabase`: Metabase dashboards (port 3000)

**Dockerfile**:
- Uses Python 3.11 slim image
- Installs uv from official image
- Caches dependencies (pyproject.toml/uv.lock)
- Exposes port 8000
- Runs `entrypoint.sh` for initialization and starts gunicorn

**Environment Variables for Docker** (in `docker-compose.yml`):
- `DB_HOST=postgres` (container name, not localhost)
- Superuser credentials can be set via `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`

## Database

Uses PostgreSQL (configured in `settings.py`):
- Supports `DATABASE_URL` (for Render, Neon, etc.)
- Falls back to individual `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` env vars

**Migrations**:
```bash
# Create a new migration after model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Reset database (caution!)
python manage.py migrate strava_integration zero
```

## Admin Interface

Accessible at `/admin/` with superuser credentials.

**Customizations** (`admin.py`):
- **AthleteAdmin**: Shows strava_id, name, location
- **ActivityAdmin**: Shows clickable Strava link for strava_id, distance in km, filters by type and date
- **MissingActivityAdmin**: Shows strava_id, detected_at, start_date_local, loaded flag; bulk actions to mark as loaded/not loaded

## Static Files & Styling

- Static files served by WhiteNoise middleware (`whitenoise.middleware.WhiteNoiseMiddleware`)
- Collected to `staticfiles/` directory
- Compressed and manifest-based storage for production

## Notable Implementation Details

**Token Refresh Mechanism** (`utils.py`):
- Tokens expire within ~6 hours; refresh happens before every API call
- New tokens are persisted to `.env` in local development (NOT recommended for production — use environment secrets)
- In production, tokens should be managed via environment variables or a secrets manager

**Activity Type Filtering**:
- The app only syncs "Ride" type activities (filters by `type == "Ride"`)
- This is hardcoded in `get_missing_ride_activities()` and can be extended if needed

**API Rate Limiting**:
- Strava allows ~100 requests per 15 minutes
- `load_missing_activities` command auto-applies 9+ second delay when loading 100+ activities
- Can be overridden with `--delay` flag

**Dry-run Detection**:
- `detect_missing_activities --dry-run` detects missing activities without persisting to DB
- Useful for testing or previewing what would be synced

**Admin Actions**:
- Bulk actions on MissingActivity to mark items as loaded/not loaded without re-fetching from Strava
- Useful if loading failed and needs retry, or if data is stale

## Testing Patterns

- Uses `@pytest.mark.django_db` to enable database access in tests
- Fixtures in `conftest.py` for creating test data
- Service functions are tested in isolation (e.g., `test_store_activity_creates_new`)
- Mocking external Strava API calls with `@patch` decorator
- Model constraints (unique strava_id) are tested to ensure data integrity

