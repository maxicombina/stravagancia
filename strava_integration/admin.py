import logging

from django.contrib import admin, messages
from django.utils.html import format_html

from .models import Athlete, Activity, MissingActivity
from .renaming import auto_rename_from_strava_data
from .services import fetch_activity_detail

logger = logging.getLogger(__name__)


@admin.action(description="Auto-rename selected activities (re-fetch from Strava)")
def auto_rename_activities(modeladmin, request, queryset):
    """
    For each selected Activity, re-fetch its detail from Strava and run the
    auto-rename pipeline. Use this when the webhook `create` arrived before
    Strava had populated the polyline, so the original auto-rename skipped.

    Synchronous and rate-limited by the internal GEOCODE_SLEEP_S; expect ~10-30s
    per activity. Don't select dozens at once.
    """
    renamed: list[tuple[int, str]] = []
    skipped: list[int] = []
    errors: list[tuple[int, str]] = []

    for activity in queryset:
        try:
            data = fetch_activity_detail(activity.strava_id)
            new_name = auto_rename_from_strava_data(data)
            if new_name:
                renamed.append((activity.strava_id, new_name))
            else:
                skipped.append(activity.strava_id)
        except Exception as exc:
            logger.exception("Admin auto-rename failed for activity %s", activity.strava_id)
            errors.append((activity.strava_id, str(exc)))

    if renamed:
        preview = ", ".join(f"{sid} → {name}" for sid, name in renamed[:3])
        suffix = " …" if len(renamed) > 3 else ""
        modeladmin.message_user(
            request,
            f"Renamed {len(renamed)}: {preview}{suffix}",
            level=messages.SUCCESS,
        )
    if skipped:
        modeladmin.message_user(
            request,
            f"Skipped {len(skipped)} (name not generic, no polyline, or non-Ride): "
            f"{', '.join(str(s) for s in skipped[:10])}",
            level=messages.WARNING,
        )
    if errors:
        preview = "; ".join(f"{sid}: {msg}" for sid, msg in errors[:3])
        modeladmin.message_user(
            request,
            f"Errored {len(errors)}: {preview}",
            level=messages.ERROR,
        )

@admin.register(Athlete)
class AthleteAdmin(admin.ModelAdmin):
    list_display = ("id", "strava_id", "first_name", "last_name", "city", "country")

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "strava_id_link", "name", "calories", "distance_km", "start_date_local", "athlete")
    list_filter = ("activity_type", "start_date_local")
    search_fields = ("name",)
    actions = [auto_rename_activities]

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