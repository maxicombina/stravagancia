import requests
from dotenv import load_dotenv
from strava_integration.utils import refresh_access_token

# Load .env vars
load_dotenv()

access_token = refresh_access_token()

url = "https://www.strava.com/api/v3/athlete"
headers = {"Authorization": f"Bearer {access_token}"}

response = requests.get(url, headers=headers)
print("Getting athlete info from Strava API...")
print(f"Status code: {response.status_code}")
print(f"Response json: {response.json()}")
