from django.contrib import admin
from .models import Athlete, Activity

@admin.register(Athlete)
class AthleteAdmin(admin.ModelAdmin):
    list_display = ("id", "strava_id", "first_name", "last_name", "city", "country")

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "strava_id", "name", "calories", "distance", "start_date", "athlete")
    list_filter = ("activity_type", "start_date")
    search_fields = ("name",)
