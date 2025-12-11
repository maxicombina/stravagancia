from django.urls import path
from . import views

urlpatterns = [
    path("test/", views.strava_test, name="strava_test"),
    path("athlete/", views.athlete_detail, name="athlete_detail"),
    path("activities_strava/", views.strava_activities, name="strava_activities"),
    path("activities/load/<int:activity_id>/", views.load_activity, name="load_activity"),
    path("dashboard/", views.strava_dashboard, name="strava_dashboard"),
    path("detect_missing_activities/", views.detect_missing_activities, name="detect_missing_activities"),
    path("load-athlete/", views.load_athlete, name="load_athlete"),
    path("missing_activities/", views.missing_activities_view, name="missing_activities"),
    path("missing/", views.MissingActivityListView.as_view(), name="missingactivities-list"),
    path("activities/", views.ActivityListView.as_view(), name="activities-list"),
]
