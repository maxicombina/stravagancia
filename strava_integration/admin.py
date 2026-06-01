import logging
import time

from django.contrib import admin, messages
from django.shortcuts import render
from django.utils.html import format_html

from .models import Athlete, Activity, MissingActivity
from .renaming import auto_rename_from_strava_data
from .services import fetch_activity_detail

logger = logging.getLogger(__name__)


def _run_rename(queryset, force: bool):
    """Helper shared by both rename actions. Returns (renamed, skipped, errors)."""
    renamed: list[tuple[int, str]] = []
    skipped: list[int] = []
    errors: list[tuple[int, str]] = []

    ids = list(queryset.values_list("strava_id", flat=True))
    run_start = time.monotonic()
    logger.info(
        "admin _run_rename start: force=%s count=%d ids=%s",
        force, len(ids), ids,
    )

    for activity in queryset:
        sid = activity.strava_id
        t0 = time.monotonic()
        try:
            logger.info("admin rename [%s]: fetching detail from Strava", sid)
            data = fetch_activity_detail(sid)
            t_fetch = time.monotonic()
            logger.info(
                "admin rename [%s]: detail fetched in %.1fs, starting auto_rename (geocoding)",
                sid, t_fetch - t0,
            )
            new_name = auto_rename_from_strava_data(data, force=force)
            t_done = time.monotonic()
            logger.info(
                "admin rename [%s]: auto_rename done in %.1fs (total %.1fs) -> %r",
                sid, t_done - t_fetch, t_done - t0, new_name,
            )
            if new_name:
                renamed.append((sid, new_name))
            else:
                skipped.append(sid)
        except Exception as exc:
            logger.exception(
                "admin rename [%s]: FAILED after %.1fs: %s",
                sid, time.monotonic() - t0, exc,
            )
            errors.append((sid, str(exc)))

    logger.info(
        "admin _run_rename done in %.1fs: renamed=%d skipped=%d errors=%d",
        time.monotonic() - run_start, len(renamed), len(skipped), len(errors),
    )
    return renamed, skipped, errors


def _report(modeladmin, request, renamed, skipped, errors, *, skip_label):
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
            f"Skipped {len(skipped)} ({skip_label}): "
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


@admin.action(description="Auto-rename selected activities (re-fetch from Strava)")
def auto_rename_activities(modeladmin, request, queryset):
    """
    For each selected Activity, re-fetch its detail from Strava and run the
    auto-rename pipeline. Use this when the webhook `create` arrived before
    Strava had populated the polyline, so the original auto-rename skipped.

    Synchronous and rate-limited by the internal GEOCODE_SLEEP_S; expect ~10-30s
    per activity. Don't select dozens at once.
    """
    renamed, skipped, errors = _run_rename(queryset, force=False)
    _report(
        modeladmin, request, renamed, skipped, errors,
        skip_label="name not generic, no polyline, or non-Ride",
    )


@admin.action(description="Force auto-rename selected (bypass generic-name check)")
def force_auto_rename_activities(modeladmin, request, queryset):
    """
    Like `auto_rename_activities` but bypasses the is_generic_name check, so it
    will rename activities even if their current name looks custom. Other gates
    (type=Ride, polyline present, distance >= 1km) still apply.

    Shows a confirmation page listing the activities before executing, since
    overwriting a custom name is destructive.
    """
    if request.POST.get("post") != "yes":
        return render(
            request,
            "admin/strava_integration/force_rename_confirm.html",
            {
                "activities": queryset,
                "action_checkbox_name": admin.helpers.ACTION_CHECKBOX_NAME,
                "opts": modeladmin.model._meta,
            },
        )

    renamed, skipped, errors = _run_rename(queryset, force=True)
    _report(
        modeladmin, request, renamed, skipped, errors,
        skip_label="no polyline, non-Ride, distance<1km, or generated name empty",
    )

@admin.register(Athlete)
class AthleteAdmin(admin.ModelAdmin):
    list_display = ("id", "strava_id", "first_name", "last_name", "city", "country")

@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "strava_id_link", "name", "calories", "distance_km", "start_date_local", "athlete")
    list_filter = ("activity_type", "start_date_local")
    search_fields = ("name",)
    actions = [auto_rename_activities, force_auto_rename_activities]

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