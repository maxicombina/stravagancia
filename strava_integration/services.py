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


def get_activities(per_page=50, after=0):
    """Fetch all activities from Strava."""
    access_token = refresh_access_token()
    all_activities = []
    page = 1
    url = f"{STRAVA_API_BASE}/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}

    while True:
        #print(f"Fetching {per_page} activities from Strava, page: {page}")
        params = {"page": page, "per_page": per_page, "after": after}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        activities = response.json()
        #print(f"Fetched {len(activities)} activities from Strava.")

        if not activities:
            break
        all_activities.extend(activities)
        page += 1

    #print(f"Fetched {len(all_activities)} activities from Strava.")
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
        #"timezone": data.get("timezone"),
        "utc_offset": data.get("utc_offset"),
        "start_date_local": parse_datetime(data.get("start_date_local")),
        "average_speed": data.get("average_speed"),
        "max_speed": data.get("max_speed"),
        "calories": data.get("calories"),
        "average_heartrate": data.get("average_heartrate"),
        "max_heartrate": data.get("max_heartrate"),
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
    # Fetch laters activities from Strava API
    latest = MissingActivity.objects.order_by('-start_date_local').first()
    after_ts = int(latest.start_date_local.timestamp()) if latest else 0
    #print(f"after_ts: {after_ts}")
    # Only get latest activities after the latest missing one
    strava_activities = get_activities(per_page=150, after=after_ts)
    # Filter to only "Ride" type
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

# strava_integration/services.py
from .models import MissingActivity

def detect_and_save_missing_activities(dry_run=False):
    """
    Detect activities present in Strava but not in the local DB.
    If dry_run=True, only detect without saving to MissingActivity.
    Otherwise, save new ones with loaded=False.
    Returns a summary dict.
    """
    missing_activities = get_missing_ride_activities()["missing_activities"]

    new_added = 0
    already_present_unloaded = 0
    already_present_loaded = 0

    for missing_activity in missing_activities:
        strava_id = missing_activity["id"]
        start_date_local = missing_activity["start_date_local"]
        if dry_run:
            # Only check if present
            obj = MissingActivity.objects.filter(
                strava_id=strava_id,
                start_date_local=start_date_local
            ).first()
            if obj:
                if obj.loaded:
                    already_present_loaded += 1
                else:
                    already_present_unloaded += 1
            else:
                new_added += 1
        else:
            # Get/create the MissingActivity
            obj, created = MissingActivity.objects.get_or_create(
                strava_id=strava_id,
                start_date_local=start_date_local,
                defaults={"loaded": False},
            )
            if created:
                new_added += 1
            else:
                if obj.loaded:
                    already_present_loaded += 1
                else:
                    already_present_unloaded += 1

    total_missing = len(missing_activities)

    return {
        "total_missing_detected": total_missing,
        "new_missing_added": new_added,
        "already_present_unloaded": already_present_unloaded,
        "already_present_loaded": already_present_loaded,
    }
