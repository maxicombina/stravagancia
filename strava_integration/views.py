# strava_integration/views.py
from django.shortcuts import render
from .services import get_strava_athlete
from .models import Athlete
from .utils import get_strava_activities
from django.utils.dateparse import parse_datetime

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

def athlete_detail(request):
    """Display the athlete stored in the database."""
    try:
        athlete = Athlete.objects.first()  # For now we just take the first one
    except Athlete.DoesNotExist:
        athlete = None

    return render(request, "strava_integration/athlete_detail.html", {"athlete": athlete})


def strava_activities(request):
    """Render a simple HTML page showing athlete activities (paginated)."""

    try:
        activities = get_strava_activities(per_page=200)

        # Filter only cycling activities (type == "Ride")
        ride_activities = [a for a in activities if a.get("type") == "Ride"]

        # Convert distance from meters to kilometers
        for a in ride_activities:
            a["distance_km"] = round(a["distance"] / 1000, 2)
            print(a["id"])

        total_count = len(ride_activities)
        return render(
            request,
            "strava_integration/strava_activities.html",
            {"activities": ride_activities, "total_count": total_count},
        )
    except Exception as e:
        return render(
            request,
            "strava_integration/strava_activities.html",
            {"error": str(e)},
        )



# load and store 1 activity
from django.shortcuts import get_object_or_404
from .models import Athlete, Activity
from .utils import get_strava_activity

def load_activity(request, activity_id):
    """Fetch a single Strava activity and store/update it in the DB."""

    # Get activity data
    data = get_strava_activity(activity_id)

    # Find athlete to associate with
    athlete_data = data.get("athlete", {})
    athlete = Athlete.objects.filter(strava_id=athlete_data.get("id")).first()
    if not athlete:
        athlete = Athlete.objects.first()

    # Prepare defaults for Activity
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
        "average_speed": data.get("average_speed"),
        "max_speed": data.get("max_speed"),
        "calories": data.get("calories"),
    }

    # Create or update
    activity, created = Activity.objects.update_or_create(
        strava_id=data["id"],
        defaults=defaults,
    )

    msg = {
        "status": "created" if created else "updated",
        "activity_id": activity.strava_id,
        "name": activity.name,
        "distance_km": round(activity.distance / 1000, 2),
        "start_date": str(activity.start_date),
    }

    formatted_json = json.dumps(msg, indent=2)
    return render(request, "strava_integration/strava_test.html", {"json_data": formatted_json})
