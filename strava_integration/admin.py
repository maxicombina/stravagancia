from django.contrib import admin
from django.utils.html import format_html
from .models import Athlete, Activity, MissingActivity

@admin.register(Athlete)
class AthleteAdmin(admin.ModelAdmin):
    list_display = ("id", "strava_id", "first_name", "last_name", "city", "country")

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "strava_id_link", "name", "calories", "distance_km", "start_date_local", "athlete")
    list_filter = ("activity_type", "start_date_local")
    search_fields = ("name",)

    @admin.display(description="Strava ID", ordering="strava_id")
    def strava_id_link(self, obj):
        """Clickable link to the Strava activity."""
        return format_html(
        '<a href="{}" target="_blank">{}</a>',
        obj.activity_url,
        obj.strava_id
    )

    @admin.display(description="Distance KM", ordering="distance")
    def distance_km(self, obj):
        """Distance in kilometers."""
        return obj.distance_km

@admin.action(description="Mark as NOT loaded (Loaded = False)")
def mark_as_not_loaded(modeladmin, request, queryset):
    updated = queryset.update(loaded=False)
    modeladmin.message_user(request, f"{updated} activities marked as not loaded.")

@admin.action(description="Mark as loaded (Loaded = True)")
def mark_as_loaded(modeladmin, request, queryset):
    updated = queryset.update(loaded=True)
    modeladmin.message_user(request, f"{updated} activities marked as loaded.")

@admin.register(MissingActivity)
class MissingActivityAdmin(admin.ModelAdmin):
    list_display = ("strava_id", "detected_at", "start_date_local", "loaded")
    list_filter = ("loaded",)
    ordering = ("-start_date_local",)
    actions = [mark_as_not_loaded, mark_as_loaded]