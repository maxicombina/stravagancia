import os
import requests

from dotenv import load_dotenv

load_dotenv()

def get_strava_athlete():
    """Fetch athlete info from Strava API, refreshing token if needed."""
    from .utils import refresh_access_token

    def fetch_athlete(access_token):
        """Do the actual request."""
        url = "https://www.strava.com/api/v3/athlete"
        headers = {"Authorization": f"Bearer {access_token}"}
        response = requests.get(url, headers=headers)
        if response.status_code == 401:
            # Token expired or invalid
            raise PermissionError("Access token expired")
        response.raise_for_status()
        return response.json()

    env_access_token = os.getenv("STRAVA_ACCESS_TOKEN")
    if not env_access_token:
        raise ValueError("Missing STRAVA_ACCESS_TOKEN in .env")

    try:
        # Try first with current token
        return fetch_athlete(env_access_token)
    except PermissionError:
        # Refresh token and retry once
        new_token = refresh_access_token()
        return fetch_athlete(new_token)