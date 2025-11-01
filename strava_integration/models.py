# strava_integration/models.py

from django.db import models

class Athlete(models.Model):
    """
    Represents a Strava athlete.
    """
    strava_id = models.BigIntegerField(unique=True)  # ID from Strava
    first_name = models.CharField(max_length=100, blank=True, null=True)
    last_name = models.CharField(max_length=100, blank=True, null=True)
    username = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    profile = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)  # when added to DB
    updated_at = models.DateTimeField(auto_now=True)      # last update

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.strava_id})"
