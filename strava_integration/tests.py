import json

import pytest
from django.test import Client
from django.utils import timezone
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Model: Athlete
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_athlete_str(athlete):
    assert str(athlete) == "John Doe (12345678)"


@pytest.mark.django_db
def test_athlete_fields(athlete):
    assert athlete.strava_id == 12345678
    assert athlete.first_name == "John"
    assert athlete.last_name == "Doe"
    assert athlete.city == "Buenos Aires"
    assert athlete.country == "Argentina"


# ---------------------------------------------------------------------------
# Model: Activity
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_activity_str(activity):
    expected_date = activity.start_date.date()
    assert str(activity) == f"Morning Ride (Ride) - {expected_date}"


@pytest.mark.django_db
def test_activity_distance_km(activity):
    # 35000 m → 35.0 km
    assert activity.distance_km == 35.0


@pytest.mark.django_db
def test_activity_url(activity):
    assert activity.activity_url == f"https://www.strava.com/activities/{activity.strava_id}"


@pytest.mark.django_db
def test_activity_belongs_to_athlete(activity, athlete):
    assert activity.athlete == athlete


@pytest.mark.django_db
def test_activity_ordering(db, athlete):
    """Activities should be ordered by start_date descending."""
    from strava_integration.models import Activity

    older = Activity.objects.create(
        athlete=athlete,
        strava_id=1001,
        name="Old Ride",
        distance=10000,
        moving_time=1800,
        elapsed_time=1900,
        total_elevation_gain=50,
        activity_type="Ride",
        start_date=timezone.now() - timezone.timedelta(days=5),
    )
    newer = Activity.objects.create(
        athlete=athlete,
        strava_id=1002,
        name="New Ride",
        distance=20000,
        moving_time=3600,
        elapsed_time=3700,
        total_elevation_gain=100,
        activity_type="Ride",
        start_date=timezone.now(),
    )

    activities = list(Activity.objects.all())
    assert activities[0] == newer
    assert activities[1] == older


# ---------------------------------------------------------------------------
# Model: MissingActivity
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_missing_activity_str(db):
    from strava_integration.models import MissingActivity

    ma = MissingActivity.objects.create(strava_id=7777001)
    assert str(ma) == "7777001"


@pytest.mark.django_db
def test_missing_activity_defaults(db):
    from strava_integration.models import MissingActivity

    ma = MissingActivity.objects.create(strava_id=7777002)
    assert ma.loaded is False
    assert ma.detected_at is not None


# ---------------------------------------------------------------------------
# Model constraints: unique strava_id
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_duplicate_athlete_strava_id_raises(db):
    """Two Athletes with the same strava_id should raise IntegrityError."""
    from django.db import IntegrityError
    from strava_integration.models import Athlete

    Athlete.objects.create(strava_id=9900001, first_name="Alice")
    with pytest.raises(IntegrityError):
        Athlete.objects.create(strava_id=9900001, first_name="Bob")


@pytest.mark.django_db
def test_duplicate_activity_strava_id_raises(athlete):
    """Two Activities with the same strava_id should raise IntegrityError."""
    from django.db import IntegrityError
    from strava_integration.models import Activity

    common = dict(
        athlete=athlete,
        name="Ride",
        distance=10000,
        moving_time=1800,
        elapsed_time=1900,
        total_elevation_gain=50,
        activity_type="Ride",
        start_date=timezone.now(),
    )
    Activity.objects.create(strava_id=9900002, **common)
    with pytest.raises(IntegrityError):
        Activity.objects.create(strava_id=9900002, **common)


@pytest.mark.django_db
def test_duplicate_missing_activity_strava_id_raises(db):
    """Two MissingActivities with the same strava_id should raise IntegrityError."""
    from django.db import IntegrityError
    from strava_integration.models import MissingActivity

    MissingActivity.objects.create(strava_id=9900003)
    with pytest.raises(IntegrityError):
        MissingActivity.objects.create(strava_id=9900003)


# ---------------------------------------------------------------------------
# Service: store_activity_from_strava_data
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_store_activity_creates_new(athlete, strava_activity_payload):
    from strava_integration.services import store_activity_from_strava_data
    from strava_integration.models import Activity

    activity, created = store_activity_from_strava_data(strava_activity_payload)

    assert created is True
    assert activity.strava_id == strava_activity_payload["id"]
    assert activity.name == "Evening Ride"
    assert activity.distance == 42000.0
    assert activity.calories == 950.0
    assert activity.athlete == athlete


@pytest.mark.django_db
def test_store_activity_updates_existing(athlete, strava_activity_payload):
    from strava_integration.services import store_activity_from_strava_data

    # First call: creates it
    store_activity_from_strava_data(strava_activity_payload)

    # Second call with updated name: should update, not create
    strava_activity_payload["name"] = "Updated Ride"
    activity, created = store_activity_from_strava_data(strava_activity_payload)

    assert created is False
    assert activity.name == "Updated Ride"


@pytest.mark.django_db
def test_store_activity_distance_km(athlete, strava_activity_payload):
    from strava_integration.services import store_activity_from_strava_data

    activity, _ = store_activity_from_strava_data(strava_activity_payload)
    # 42000 m → 42.0 km
    assert activity.distance_km == 42.0


# ---------------------------------------------------------------------------
# Service: detect_and_save_missing_activities
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_detect_saves_missing_activity(athlete):
    """When Strava has a Ride not in local DB, it should be saved as MissingActivity."""
    from strava_integration.services import detect_and_save_missing_activities
    from strava_integration.models import MissingActivity

    fake_strava_activities = [
        {
            "id": 5551001,
            "type": "Ride",
            "start_date_local": "2026-02-01T08:00:00Z",
        }
    ]

    with patch("strava_integration.services.get_activities", return_value=fake_strava_activities):
        result = detect_and_save_missing_activities()

    assert result["new_missing_added"] == 1
    assert MissingActivity.objects.filter(strava_id=5551001).exists()


@pytest.mark.django_db
def test_detect_skips_already_loaded_activity(athlete):
    """A Ride already in Activity DB should not appear as missing."""
    from strava_integration.services import detect_and_save_missing_activities
    from strava_integration.models import Activity, MissingActivity

    Activity.objects.create(
        athlete=athlete,
        strava_id=5551002,
        name="Already Loaded",
        distance=10000,
        moving_time=1800,
        elapsed_time=1900,
        total_elevation_gain=50,
        activity_type="Ride",
        start_date=timezone.now(),
    )

    fake_strava_activities = [
        {
            "id": 5551002,
            "type": "Ride",
            "start_date_local": "2026-02-02T08:00:00Z",
        }
    ]

    with patch("strava_integration.services.get_activities", return_value=fake_strava_activities):
        result = detect_and_save_missing_activities()

    assert result["new_missing_added"] == 0
    assert not MissingActivity.objects.filter(strava_id=5551002).exists()


@pytest.mark.django_db
def test_detect_dry_run_does_not_save(athlete):
    """dry_run=True should detect but not persist MissingActivity records."""
    from strava_integration.services import detect_and_save_missing_activities
    from strava_integration.models import MissingActivity

    fake_strava_activities = [
        {
            "id": 5551003,
            "type": "Ride",
            "start_date_local": "2026-02-03T08:00:00Z",
        }
    ]

    with patch("strava_integration.services.get_activities", return_value=fake_strava_activities):
        result = detect_and_save_missing_activities(dry_run=True)

    assert result["new_missing_added"] == 1
    assert not MissingActivity.objects.filter(strava_id=5551003).exists()


# ---------------------------------------------------------------------------
# Webhook: auto-rename thread dispatch
# ---------------------------------------------------------------------------

WEBHOOK_URL = "/archive/strava/webhook/strava/"


def _post_webhook(client, event: dict):
    return client.post(
        WEBHOOK_URL,
        data=json.dumps(event),
        content_type="application/json",
    )


def _fake_activity_payload():
    return {
        "id": 99001,
        "name": "Morning Ride",
        "type": "Ride",
        "distance": 30000.0,
        "map": {"summary_polyline": "fake-poly"},
    }


@pytest.mark.django_db
def test_webhook_create_dispatches_rename_thread(athlete):
    """On aspect_type=create the thread must be dispatched with _safe_auto_rename."""
    client = Client()
    payload = _fake_activity_payload()

    with patch("strava_integration.views.fetch_activity_detail", return_value=payload), \
         patch("strava_integration.views.store_activity_from_strava_data") as store_mock, \
         patch("strava_integration.views.threading.Thread") as thread_cls:
        resp = _post_webhook(client, {
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 99001,
        })

    assert resp.status_code == 200
    store_mock.assert_called_once_with(payload)
    thread_cls.assert_called_once()
    kwargs = thread_cls.call_args.kwargs
    from strava_integration.views import _safe_auto_rename
    assert kwargs["target"] is _safe_auto_rename
    assert kwargs["args"] == (payload,)
    assert kwargs["daemon"] is True
    # And .start() must have been called.
    thread_cls.return_value.start.assert_called_once()


@pytest.mark.django_db
def test_webhook_update_does_NOT_dispatch_rename_thread(athlete):
    """Loop prevention: aspect_type=update must NEVER trigger a rename."""
    client = Client()
    payload = _fake_activity_payload()

    with patch("strava_integration.views.fetch_activity_detail", return_value=payload), \
         patch("strava_integration.views.store_activity_from_strava_data"), \
         patch("strava_integration.views.threading.Thread") as thread_cls:
        resp = _post_webhook(client, {
            "object_type": "activity",
            "aspect_type": "update",
            "object_id": 99001,
        })

    assert resp.status_code == 200
    thread_cls.assert_not_called()


@pytest.mark.django_db
def test_webhook_delete_does_NOT_dispatch_rename_thread(activity):
    """Delete must not trigger a rename either — it only deletes."""
    client = Client()

    with patch("strava_integration.views.threading.Thread") as thread_cls:
        resp = _post_webhook(client, {
            "object_type": "activity",
            "aspect_type": "delete",
            "object_id": activity.strava_id,
        })

    assert resp.status_code == 200
    thread_cls.assert_not_called()


@pytest.mark.django_db
def test_safe_auto_rename_swallows_exceptions():
    """_safe_auto_rename must not propagate — only log."""
    from strava_integration.views import _safe_auto_rename

    with patch("strava_integration.views.auto_rename_from_strava_data",
               side_effect=RuntimeError("boom")):
        # Must not raise.
        _safe_auto_rename({"id": 42})


@pytest.mark.django_db
def test_webhook_create_does_not_block_on_thread(athlete):
    """
    The handler must return without waiting for the thread.
    We verify that Thread().start() is called (not Thread().run()) — start is
    asynchronous, run is synchronous.
    """
    client = Client()
    payload = _fake_activity_payload()

    with patch("strava_integration.views.fetch_activity_detail", return_value=payload), \
         patch("strava_integration.views.store_activity_from_strava_data"), \
         patch("strava_integration.views.threading.Thread") as thread_cls:
        _post_webhook(client, {
            "object_type": "activity",
            "aspect_type": "create",
            "object_id": 99001,
        })

    thread_instance = thread_cls.return_value
    thread_instance.start.assert_called_once()
    thread_instance.run.assert_not_called()
