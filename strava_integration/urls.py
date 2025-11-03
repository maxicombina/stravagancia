from django.urls import path
from . import views

urlpatterns = [
    path("test/", views.strava_test, name="strava_test"),
    path("athlete/", views.athlete_detail, name="athlete_detail"),
    path("activities/", views.strava_activities, name="strava_activities"),
    path("activities/load/<int:activity_id>/", views.load_activity, name="load_activity"),
]
