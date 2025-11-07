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


class Activity(models.Model):
    """
    Represents a Strava activity.
    """
    athlete = models.ForeignKey('Athlete', on_delete=models.CASCADE, related_name='activities')
    strava_id = models.BigIntegerField(unique=True)
    name = models.CharField(max_length=255)
    distance = models.FloatField()  # meters
    moving_time = models.IntegerField()  # seconds
    elapsed_time = models.IntegerField()  # seconds
    total_elevation_gain = models.FloatField()  # meters
    activity_type = models.CharField(max_length=50) #field 'type'
    sport_type = models.CharField(max_length=50, blank=True, null=True)
    start_date = models.DateTimeField()
    timezone = models.CharField(max_length=100, blank=True, null=True)
    utc_offset = models.FloatField(blank=True, null=True)
    average_speed = models.FloatField(null=True, blank=True)
    max_speed = models.FloatField(null=True, blank=True)
    calories = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ['-start_date']  # el "-" make it descending

    def __str__(self):
        return f"{self.name} ({self.activity_type}) - {self.start_date.date()}"

class MissingActivity(models.Model):
    """
    Stores Strava activity IDs that exist in Strava but are not yet loaded locally.
    """
    strava_id = models.BigIntegerField(unique=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    loaded = models.BooleanField(default=False)  # loaded locally in DB

    def __str__(self):
        return str(self.strava_id)
