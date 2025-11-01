# strava_integration/views.py
from django.shortcuts import render
from .services import get_strava_athlete
import json

def strava_test(request):
    """Render a pretty HTML page showing athlete JSON."""
    try:
        athlete_data = get_strava_athlete()
        formatted_json = json.dumps(athlete_data, indent=2)
        return render(request, "strava_integration/strava_test.html", {"json_data": formatted_json})
    except Exception as e:
        # in case of error, show the error message in the template
        return render(request, "strava_integration/strava_test.html", {"json_data": str(e)})
