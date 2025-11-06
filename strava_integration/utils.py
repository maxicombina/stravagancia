import os
import requests
from dotenv import load_dotenv

load_dotenv()

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")

def refresh_access_token():
    """
    Refresh Strava access token using the refresh token.
    Returns the access token string.
    """
    url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": STRAVA_REFRESH_TOKEN,
    }
    response = requests.post(url, data=payload)
    response.raise_for_status()
    tokens = response.json()

    # Update .env automatically
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

