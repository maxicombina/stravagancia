import os
import requests
from dotenv import load_dotenv

load_dotenv()

def get_strava_athlete():
    """Fetch athlete info from Strava API using the access token."""
    access_token = os.getenv("STRAVA_ACCESS_TOKEN")
    if not access_token:
        raise ValueError("Missing STRAVA_ACCESS_TOKEN in .env")

    url = "https://www.strava.com/api/v3/athlete"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(url, headers=headers)
    response.raise_for_status()

    return response.json()
