import os
import requests
from dotenv import load_dotenv


# Load .env vars
load_dotenv()

ACCESS_TOKEN = os.getenv("STRAVA_ACCESS_TOKEN")

url = "https://www.strava.com/api/v3/athlete"
headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

response = requests.get(url, headers=headers)
print(response.status_code)
print(response.json())
