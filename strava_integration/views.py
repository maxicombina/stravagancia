from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import Athlete, Activity, MissingActivity
from .services import (
    get_strava_athlete,
    fetch_and_store_athlete,
    get_activities,
    get_missing_ride_activities,
    fetch_activity_detail,
    store_activity_from_strava_data,
)
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

def strava_dashboard(request):
    """Simple dashboard page with buttons for Strava sync steps."""
    return render(request, "strava_integration/strava_dashboard.html")


def strava_activities(request):
    """Show Strava activities (type Ride)."""
    try:
        activities = get_activities(per_page=200)
        rides = [a for a in activities if a.get("type") == "Ride"]
        for a in rides:
            a["distance_km"] = round(a["distance"] / 1000, 2)
        return render(
            request,
            "strava_integration/strava_activities.html",
            {"activities": rides, "total_count": len(rides)},
        )
    except Exception as e:
        return render(
            request,
            "strava_integration/strava_activities.html",
            {"error": str(e)},
        )


def load_athlete(request):
    """Call Strava API and store/update athlete."""
    athlete, created = fetch_and_store_athlete()
    msg = "Created new athlete" if created else "Updated existing athlete"
    data = {
        "message": msg,
        "athlete": {
            "strava_id": athlete.strava_id,
            "first_name": athlete.first_name,
            "last_name": athlete.last_name,
            "username": athlete.username,
            "city": athlete.city,
            "country": athlete.country,
            "profile": athlete.profile,
        },
    }
    return JsonResponse(data)


def load_activity(request, activity_id):
    """Fetch a single Strava activity and store/update it."""
    data = fetch_activity_detail(activity_id)
    activity, created = store_activity_from_strava_data(data)
    msg = {
        "status": "created" if created else "updated",
        "activity_id": activity.strava_id,
        "name": activity.name,
        "distance_km": round(activity.distance / 1000, 2),
    }
    return JsonResponse(msg)

def missing_activities_view(request):
    missing_activities = get_missing_ride_activities()
    return JsonResponse({"missing_activities": missing_activities, "count": len(missing_activities)})

def detect_missing_activities(request):
    """
    Detect activities present in Strava but not in the local DB,
    save any new ones into MissingActivity (loaded=False by default),
    and return a JSON summary.
    """
    try:
        missing_activities = get_missing_ride_activities() ["missing_activities"]

        new_added = 0
        already_present_unloaded = 0
        already_present_loaded = 0

        for missing_activity in missing_activities:
            obj, created = MissingActivity.objects.get_or_create(
                strava_id=missing_activity["id"],
                start_date_local=missing_activity["start_date_local"],
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

        return JsonResponse({
            "status": "ok",
            "total_missing_detected": total_missing,
            "new_missing_added": new_added,
            "already_present_unloaded": already_present_unloaded,
            "already_present_loaded": already_present_loaded,
        })
    except Exception as e:
        return JsonResponse({
            "status": "error",
            "message": str(e),
        }, status=500)
