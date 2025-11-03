# strava_integration/utils.py
import os
import requests
from .models import Athlete

from dotenv import load_dotenv

load_dotenv()

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")


STRAVA_API_BASE = "https://www.strava.com/api/v3"

def refresh_access_token():
    """
    Refresh Strava access token using the refresh token.
    """
    url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": STRAVA_REFRESH_TOKEN
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    tokens = response.json()

    # Update .env file automatically
    with open(".env", "r") as f:
        lines = f.readlines()
    with open(".env", "w") as f:
        for line in lines:
            if line.startswith("STRAVA_ACCESS_TOKEN="):
                f.write(f"STRAVA_ACCESS_TOKEN={tokens['access_token']}\n")
            elif line.startswith("STRAVA_REFRESH_TOKEN="):
                f.write(f"STRAVA_REFRESH_TOKEN={tokens['refresh_token']}\n")
            else:
                f.write(line)

    return tokens["access_token"]

def fetch_and_save_athlete_with_refresh():
    """
    Refresh access token, get athlete info from Strava, and save to DB.
    Returns (Athlete object, new_refresh_token)
    """
    # Refresh token
    token_data = refresh_access_token()
    access_token = token_data["access_token"]
    new_refresh_token = token_data["refresh_token"]

    # Call Strava API
    url = f"{STRAVA_API_BASE}/athlete"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()

    # Store in DB
    athlete, created = Athlete.objects.update_or_create(
        strava_id=data["id"],
        defaults={
            "first_name": data.get("firstname"),
            "last_name": data.get("lastname"),
            "username": data.get("username"),
            "city": data.get("city"),
            "country": data.get("country"),
            "profile": data.get("profile")
        }
    )

    return athlete, new_refresh_token


def get_strava_activities(per_page=50):
    """
    Fetch a page of athlete activities from Strava API.
    Handles token expiration and refresh automatically.
    """
    access_token = refresh_access_token()

    all_activities = []
    page = 1

    if not access_token:
        raise ValueError("Missing STRAVA_ACCESS_TOKEN in .env")

    url = f"{STRAVA_API_BASE}/athlete/activities"
    headers = {"Authorization": f"Bearer {access_token}"}

    while True:
        params = {"page": page, "per_page": per_page}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        activities = response.json()

        #print(activities)
        #print (page)
        if not activities:
            break  # no more pages

        all_activities.extend(activities)

        page += 1

    return all_activities

def get_strava_activity(activity_id):
    """
    Fetch a single activity by ID from Strava API.
    """
    access_token = os.getenv("STRAVA_ACCESS_TOKEN")
    if not access_token:
        raise ValueError("Missing STRAVA_ACCESS_TOKEN in .env")

    url = f"https://www.strava.com/api/v3/activities/{activity_id}"
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()
