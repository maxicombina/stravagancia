# What's this about
A project to learn Python+Django by creating a small web app to track my Strava Ride activities.

# Why
On one hand, I am learning Python+Django.

On the other hand, I want to keep track of my personal Strava Ride activities and be able to visualize data in ways which are not always present in Strava nor Garmin Connect.

So, why not?
It's a good excuse to learn something new and useful, while being able to view my Ride data in the way I want.

# What does it do?
- Loads one Strava athlete
- Stores all the Ride activities
- Detects missing activities, and ability to load only those
- Leverages the Django admin interface to manage models
- Using docker (with the provided `docker-compose.yml`, a Metabase instance can be launched to visualize the data

# Known issues and limitations
- Only one user supported
- Docker not used for Django, only for Metabase and Postgres. This is to keep things simple and avoid the overhead of managing multiple containers. The Django app can be run locally without Docker, and it will connect to the Postgres database running in Docker.

# Next steps
- Improve some basic visualizations of the data (e.g., total distance per month, average speed, calories per month)
- Have a simple web interface to view and potentially manipulate some of the data
- Get this project to live in the Cloud (check: Heroku)
- Use Strava webhooks to get notified of new activities
- Use Grafana instead of Metabase for visualization, and connect it to the Postgres database
- Resources:
  - https://medium.com/@codingforinnovations/deploying-a-django-app-to-production-with-vercel-in-less-than-8-minutes-0877a21af4f3
  - https://neon.com/ database

## Further improvements
- Tests
- `@make_as_endpoint("/activity")` -> new decorator to automatically add endpoints
- `@store_in_db(Activity)` # Or any model -> store in DB
- Used to decorate functions such as:
    ```
    def fetch_activity(id):
        return request.get(....)
    ```

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
- Initialize the database and load data:
  - `docker compose up -d postgres`
  - `python manage.py migrate`
  - `python manage.py createsuperuser`
  - `python test_strava_connection.py` (to verify Strava API access)
  - `python manage.py load_athlete`
  - `python manage.py detect_missing_activities`
  - `python manage.py load_missing_activities`: may take a while depending on how many activities you have
- Optionally: Run metabase using docker-compose:
  - `docker-compose up` (Will launch Metabase on port 3000)
- Optionally: run the Django development server:
  - `python manage.py runserver`
  - Access the admin interface at http://localhost:8000/admin using the superuser credentials created before.
  - Some basic URLs are already wired up in strava_integration/urls.py for exploration.

Auth in metabase:
- email: admin@admin.com  
- password: django-strava-01
