##
## Call to external Strava API and business logic.
##

import os
import requests
from django.utils.dateparse import parse_datetime
from .models import Athlete, Activity
from .utils import refresh_access_token

STRAVA_API_BASE = "https://www.strava.com/api/v3"


# TODO: de-duplicate with fetch_and_store_athlete() below
def get_strava_athlete():
     """Fetch athlete info from Strava API, refreshing token if needed."""
     access_token = refresh_access_token()
     url = f"{STRAVA_API_BASE}/athlete"
     headers = {"Authorization": f"Bearer {access_token}"}
     response = requests.get(url, headers=headers)
     if response.status_code == 401:
         # Token expired or invalid
         raise PermissionError("Access token expired")
         response.raise_for_status()
     return response.json()


def fetch_and_store_athlete():
    """
    Refresh token, fetch athlete from Strava, store/update in DB.
    """
    access_token = refresh_access_token()
    url = f"{STRAVA_API_BASE}/athlete"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()

    athlete_info = {
        "strava_id": data["id"],
        "first_name": data.get("firstname"),
        "last_name": data.get("lastname"),
        "username": data.get("username"),
        "city": data.get("city"),
        "country": data.get("country"),
        "profile": data.get("profile"),
    }

    athlete, created = Athlete.objects.update_or_create(
        strava_id=athlete_info["strava_id"], defaults=athlete_info
    )
    return athlete, created


def get_activities(per_page=50):
    """Fetch all activities from Strava."""
    access_token = refresh_access_token()
    all_activities = []
    page = 1
    url = f"{STRAVA_API_BASE}/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}

    while True:
        params = {"page": page, "per_page": per_page}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        activities = response.json()
        if not activities:
            break
        all_activities.extend(activities)
        page += 1
    return all_activities


def fetch_activity_detail(activity_id):
    """Fetch single activity by ID."""
    access_token = os.getenv("STRAVA_ACCESS_TOKEN")
    url = f"{STRAVA_API_BASE}/activities/{activity_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def store_activity_from_strava_data(data):
    """Create or update an Activity model instance from Strava JSON."""
    athlete_data = data.get("athlete", {})
    athlete = Athlete.objects.filter(strava_id=athlete_data.get("id")).first()
    if not athlete:
        athlete = Athlete.objects.first()

    defaults = {
        "athlete": athlete,
        "name": data.get("name", ""),
        "distance": float(data.get("distance", 0)),
        "moving_time": int(data.get("moving_time", 0)),
        "elapsed_time": int(data.get("elapsed_time", 0)),
        "total_elevation_gain": float(data.get("total_elevation_gain", 0)),
        "activity_type": data.get("type", ""),
        "sport_type": data.get("sport_type"),
        "start_date": parse_datetime(data.get("start_date")),
        "timezone": data.get("timezone"),
        "utc_offset": data.get("utc_offset"),
        "start_date_local": parse_datetime(data.get("start_date_local")),
        "average_speed": data.get("average_speed"),
        "max_speed": data.get("max_speed"),
        "calories": data.get("calories"),
    }

    activity, created = Activity.objects.update_or_create(
        strava_id=data["id"],
        defaults=defaults,
    )

    return activity, created

def get_missing_ride_activities():
    """
    Compare the list of Strava activities with those stored in the database,
    and return the list of IDs that are missing locally, and are Ride type,
    including their start_date_local.
    """
    # Fetch all activities from Strava API
    strava_activities = get_activities(per_page=150)
    rides = [a for a in strava_activities if a.get("type") == "Ride"]

    # Convert to dict {id: start_date_local}
    strava_ride_map = {
        a["id"]: a.get("start_date_local")
        for a in rides
    }

    # Fetch all stored activity IDs from DB
    db_ids = set(Activity.objects.values_list("strava_id", flat=True))

    # Determine which IDs are missing
    missing_ids = sorted(list(set(strava_ride_map.keys()) - db_ids))

    # Build detailed list for missing rides
    missing_activities = [
        {"id": missing_id, "start_date_local": strava_ride_map[missing_id]}
        for missing_id in missing_ids
    ]

    return {
        "strava_total": len(strava_ride_map),
        "db_total": len(db_ids),
        "missing_total": len(missing_activities),
        "missing_activities": missing_activities,
    }
