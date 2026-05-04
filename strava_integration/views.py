import os

from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import ListView
from .models import Athlete, MissingActivity, Activity
import json
from .services import (
    get_strava_athlete,
    fetch_and_store_athlete,
    get_activities,
    get_missing_ride_activities,
    fetch_activity_detail,
    store_activity_from_strava_data,
    detect_and_save_missing_activities
)

class MissingActivityListView(LoginRequiredMixin, ListView):
    model = MissingActivity
    template_name = "strava_integration/missingactivities_list.html"
    context_object_name = "missingactivities"
    ordering = ["-detected_at"]


class ActivityListView(LoginRequiredMixin, ListView):
    model = Activity
    template_name = "strava_integration/activities_list.html"
    context_object_name = "activities"
    ordering = ["-start_date_local"]

@login_required
def strava_test(request):
    """Render a pretty HTML page showing athlete JSON."""
    try:
        athlete_data = get_strava_athlete()
        formatted_json = json.dumps(athlete_data, indent=2)
        return render(request, "strava_integration/strava_test.html", {"json_data": formatted_json})
    except Exception as e:
        # in case of error, show the error message in the template
        return render(request, "strava_integration/strava_test.html", {"json_data": str(e)})

@login_required
def athlete_detail(request):
    """Display the athlete stored in the database."""
    try:
        athlete = Athlete.objects.first()  # For now we just take the first one
    except Athlete.DoesNotExist:
        athlete = None

    return render(request, "strava_integration/athlete_detail.html", {"athlete": athlete})

@login_required
def strava_dashboard(request):
    """Simple dashboard page with buttons for Strava sync steps."""
    return render(request, "strava_integration/strava_dashboard.html")


@login_required
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


@login_required
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


@login_required
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

@login_required
def missing_activities_view(request):
    missing_activities = get_missing_ride_activities()
    return JsonResponse({"missing_activities": missing_activities, "count": len(missing_activities)})

@login_required
def detect_missing_activities(request):
    """
    View to detect and save missing Strava activities,
    returns a JSON summary.
    """
    try:
        summary = detect_and_save_missing_activities()
        return JsonResponse({"status": "ok", **summary})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)



import hashlib
import hmac
import logging

logger = logging.getLogger(__name__)


@csrf_exempt
def strava_webhook(request):
    """
    Strava webhook endpoint.

    GET  — subscription verification challenge from Strava.
    POST — activity event (create / update / delete).
    """
    if request.method == "GET":
        return _handle_webhook_verification(request)
    if request.method == "POST":
        return _handle_webhook_event(request)
    return JsonResponse({"error": "method not allowed"}, status=405)


def _handle_webhook_verification(request):
    """Respond to Strava's hub challenge to verify the endpoint."""
    verify_token = os.environ.get("STRAVA_WEBHOOK_VERIFY_TOKEN", "")
    hub_mode = request.GET.get("hub.mode")
    hub_token = request.GET.get("hub.verify_token")
    hub_challenge = request.GET.get("hub.challenge")

    if hub_mode == "subscribe" and hub_token == verify_token:
        logger.info("Strava webhook verified successfully.")
        return JsonResponse({"hub.challenge": hub_challenge})

    logger.warning("Strava webhook verification failed (token mismatch).")
    return JsonResponse({"error": "forbidden"}, status=403)


def _handle_webhook_event(request):
    """Process an incoming Strava activity event."""
    try:
        event = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid json"}, status=400)

    object_type = event.get("object_type")   # "activity" or "athlete"
    aspect_type = event.get("aspect_type")   # "create", "update", "delete"
    object_id   = event.get("object_id")     # activity or athlete ID

    logger.info("Strava webhook event: %s %s id=%s", aspect_type, object_type, object_id)

    if object_type == "activity":
        if aspect_type == "create":
            try:
                data = fetch_activity_detail(object_id)
                store_activity_from_strava_data(data)
                logger.info("Activity %s stored from webhook.", object_id)
            except Exception as exc:
                logger.error("Failed to store activity %s: %s", object_id, exc)
        elif aspect_type == "delete":
            Activity.objects.filter(strava_id=object_id).delete()
            logger.info("Activity %s deleted from webhook.", object_id)
        # "update" events: re-fetch and update
        elif aspect_type == "update":
            try:
                data = fetch_activity_detail(object_id)
                store_activity_from_strava_data(data)
                logger.info("Activity %s updated from webhook.", object_id)
            except Exception as exc:
                logger.error("Failed to update activity %s: %s", object_id, exc)

    # Strava requires a 200 response within 2 seconds
    return JsonResponse({"status": "ok"})
