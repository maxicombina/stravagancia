#
# Sample script to get a Strava activity after refreshing the access token.

import os
import requests
from dotenv import load_dotenv

load_dotenv()

STRAVA_CLIENT_ID = os.getenv("STRAVA_CLIENT_ID")
STRAVA_CLIENT_SECRET = os.getenv("STRAVA_CLIENT_SECRET")
STRAVA_REFRESH_TOKEN = os.getenv("STRAVA_REFRESH_TOKEN")

# Step 1: Refresh the access token
def refresh_access_token():
    url = "https://www.strava.com/oauth/token"
    payload = {
        "client_id": STRAVA_CLIENT_ID,
        "client_secret": STRAVA_CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": STRAVA_REFRESH_TOKEN,
    }

    response = requests.post(url, data=payload)
    data = response.json()

    if "access_token" not in data:
        raise Exception(f"Failed to refresh token: {data}")

    print("Token refreshed successfully! ✅")
    return data["access_token"]

# Step 2: Get a specific activity
def get_activity(activity_id, access_token):
    url = f"https://www.strava.com/api/v3/activities/{activity_id}"
    headers = {"Authorization": f"Bearer {access_token}"}

    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        raise Exception(f"Error fetching activity: {response.status_code}, {response.text}")

    return response.json()

if __name__ == "__main__":
    access_token = refresh_access_token()
    #print(access_token)
    # 👇 replace with one of your activity IDs
    activity_id = 16306601919
    activity = get_activity(activity_id, access_token)

    # Pretty print the JSON
    import json
    print(json.dumps(activity, indent=2))
