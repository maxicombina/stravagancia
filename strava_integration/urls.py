from django.urls import path
from . import views

urlpatterns = [
    path("test/", views.strava_test, name="strava_test"),
]
