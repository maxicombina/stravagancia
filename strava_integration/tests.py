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


class _DeferredThread:
    """Stand-in for threading.Thread: start() only records; run() executes the
    target inline (in the test thread, so it sees the test DB transaction)."""

    def __init__(self, registry, target=None, args=(), kwargs=None, daemon=None, name=None):
        self.target = target
        self.args = args
        self.kwargs = kwargs or {}
        self.daemon = daemon
        self.name = name
        self.started = False
        registry.append(self)

    def start(self):
        self.started = True

    def run(self):
        self.target(*self.args, **self.kwargs)


@pytest.fixture
def deferred_threads():
    """Threads created by the webhook view, captured instead of started, with
    django.db.connections mocked in views (closing the test's connection from
    an inline worker would break the test transaction)."""
    from unittest.mock import MagicMock

    created = []
    connections_mock = MagicMock()
    with patch("strava_integration.views.threading.Thread",
               side_effect=lambda *a, **kw: _DeferredThread(created, *a, **kw)), \
         patch("strava_integration.views.connections", connections_mock):
        yield created, connections_mock


CREATE_EVENT = {"object_type": "activity", "aspect_type": "create", "object_id": 99001}


@pytest.mark.django_db
def test_webhook_create_answers_before_fetching(athlete, deferred_threads):
    """create: 200 right away; fetch/store/rename only happen in the worker."""
    from unittest.mock import MagicMock
    from strava_integration.views import _process_created_activity

    created, connections_mock = deferred_threads
    payload = _fake_activity_payload()
    calls = MagicMock()

    with patch("strava_integration.views.fetch_activity_detail", return_value=payload) as fetch_mock, \
         patch("strava_integration.views.store_activity_from_strava_data") as store_mock, \
         patch("strava_integration.views.auto_rename_from_strava_data", return_value="A - [B] ~8km spacing") as rename_mock:
        calls.attach_mock(fetch_mock, "fetch")
        calls.attach_mock(store_mock, "store")
        calls.attach_mock(rename_mock, "rename")

        resp = _post_webhook(client=Client(), event=CREATE_EVENT)

        # The response is out and nothing has been fetched or stored yet.
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
        assert calls.mock_calls == []
        (thread,) = created
        assert thread.target is _process_created_activity
        assert thread.args == (99001,)
        assert thread.daemon is True
        assert thread.name == "create-99001"
        assert thread.started is True

        thread.run()

    assert [c[0] for c in calls.mock_calls] == ["fetch", "store", "rename"]
    fetch_mock.assert_called_once_with(99001)
    store_mock.assert_called_once_with(payload)
    rename_mock.assert_called_once_with(payload)
    connections_mock.close_all.assert_called_once()


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
def test_webhook_create_skips_non_ride(athlete, deferred_threads, app_caplog):
    """A create event for a Walk/Run is skipped inside the worker: not stored, not renamed."""
    from strava_integration.models import Activity

    created, connections_mock = deferred_threads
    walk_payload = {**_fake_activity_payload(), "type": "Walk"}

    with patch("strava_integration.views.fetch_activity_detail", return_value=walk_payload) as fetch_mock, \
         patch("strava_integration.views.auto_rename_from_strava_data") as rename_mock:
        resp = _post_webhook(Client(), CREATE_EVENT)
        assert resp.status_code == 200
        (thread,) = created
        thread.run()

    fetch_mock.assert_called_once_with(99001)
    rename_mock.assert_not_called()
    assert not Activity.objects.filter(strava_id=99001).exists()
    assert any(
        "Activity 99001 skipped (create): type='Walk' is not 'Ride'" in r.getMessage()
        for r in app_caplog.records
    )
    connections_mock.close_all.assert_called_once()


@pytest.mark.django_db
def test_create_worker_stores_ride_in_db(athlete, strava_activity_payload, deferred_threads):
    """End to end through the real store: the worker persists the Ride."""
    from strava_integration.models import Activity

    created, _connections = deferred_threads
    event = {**CREATE_EVENT, "object_id": strava_activity_payload["id"]}

    with patch("strava_integration.views.fetch_activity_detail", return_value=strava_activity_payload), \
         patch("strava_integration.views.auto_rename_from_strava_data", return_value=None):
        _post_webhook(Client(), event)
        assert not Activity.objects.filter(strava_id=strava_activity_payload["id"]).exists()
        (thread,) = created
        thread.run()

    stored = Activity.objects.get(strava_id=strava_activity_payload["id"])
    assert stored.name == "Evening Ride"
    assert stored.athlete == athlete


@pytest.mark.django_db
@pytest.mark.parametrize("failing", ["fetch", "store"])
def test_create_worker_logs_errors_and_never_raises(athlete, app_caplog, failing):
    from unittest.mock import MagicMock
    from strava_integration.views import _process_created_activity

    fetch = MagicMock(return_value=_fake_activity_payload())
    store = MagicMock()
    {"fetch": fetch, "store": store}[failing].side_effect = RuntimeError("boom")
    connections_mock = MagicMock()

    with patch("strava_integration.views.fetch_activity_detail", fetch), \
         patch("strava_integration.views.store_activity_from_strava_data", store), \
         patch("strava_integration.views.auto_rename_from_strava_data") as rename_mock, \
         patch("strava_integration.views.connections", connections_mock):
        _process_created_activity(99001)  # must not raise

    rename_mock.assert_not_called()
    errors = [r for r in app_caplog.records if r.levelname == "ERROR"]
    assert [r.getMessage() for r in errors] == ["Failed to process created activity 99001: boom"]
    connections_mock.close_all.assert_called_once()


@pytest.mark.django_db
def test_create_worker_survives_close_all_failure(athlete, app_caplog):
    from unittest.mock import MagicMock
    from strava_integration.views import _process_created_activity

    connections_mock = MagicMock()
    connections_mock.close_all.side_effect = RuntimeError("socket already gone")

    with patch("strava_integration.views.fetch_activity_detail", return_value=_fake_activity_payload()), \
         patch("strava_integration.views.store_activity_from_strava_data"), \
         patch("strava_integration.views.auto_rename_from_strava_data", return_value=None), \
         patch("strava_integration.views.connections", connections_mock):
        _process_created_activity(99001)  # must not raise

    connections_mock.close_all.assert_called_once()
    assert any("socket already gone" in r.getMessage() for r in app_caplog.records)


@pytest.mark.django_db
def test_create_worker_rename_failure_is_logged_by_safe_auto_rename(athlete, app_caplog):
    """A rename exception is caught by _safe_auto_rename (its own log line);
    the activity was already stored and connections are still closed."""
    from unittest.mock import MagicMock
    from strava_integration.views import _process_created_activity

    connections_mock = MagicMock()
    with patch("strava_integration.views.fetch_activity_detail", return_value=_fake_activity_payload()), \
         patch("strava_integration.views.store_activity_from_strava_data") as store_mock, \
         patch("strava_integration.views.auto_rename_from_strava_data", side_effect=RuntimeError("geo down")), \
         patch("strava_integration.views.connections", connections_mock):
        _process_created_activity(99001)

    store_mock.assert_called_once()
    messages_ = [r.getMessage() for r in app_caplog.records if r.levelname == "ERROR"]
    assert messages_ == ["Auto-rename failed for activity 99001: geo down"]
    connections_mock.close_all.assert_called_once()


@pytest.mark.django_db
def test_webhook_update_skips_non_ride(athlete):
    """An update event for a Walk/Run must NOT be stored."""
    client = Client()
    run_payload = {**_fake_activity_payload(), "type": "Run"}

    with patch("strava_integration.views.fetch_activity_detail", return_value=run_payload), \
         patch("strava_integration.views.store_activity_from_strava_data") as store_mock:
        resp = _post_webhook(client, {
            "object_type": "activity",
            "aspect_type": "update",
            "object_id": 99001,
        })

    assert resp.status_code == 200
    store_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Admin action: auto_rename_activities
# ---------------------------------------------------------------------------

def _make_activity(athlete, strava_id, name="Morning Ride"):
    from strava_integration.models import Activity
    return Activity.objects.create(
        athlete=athlete,
        strava_id=strava_id,
        name=name,
        distance=20000,
        moving_time=1800,
        elapsed_time=1900,
        total_elevation_gain=50,
        activity_type="Ride",
        start_date=timezone.now(),
    )


@pytest.mark.django_db
def test_admin_action_renames_each_selected_activity(athlete):
    from unittest.mock import MagicMock
    from strava_integration.admin import auto_rename_activities
    from strava_integration.models import Activity

    a1 = _make_activity(athlete, 71001, "Morning Ride")
    a2 = _make_activity(athlete, 71002, "Evening Ride")

    payloads = {
        71001: {"id": 71001, "name": "Morning Ride", "type": "Ride"},
        71002: {"id": 71002, "name": "Evening Ride", "type": "Ride"},
    }

    def fake_fetch(sid):
        return payloads[sid]

    def fake_rename(data):
        return f"Renamed-{data['id']}"

    modeladmin = MagicMock()
    request = MagicMock()

    with patch("strava_integration.admin.fetch_activity_detail", side_effect=fake_fetch), \
         patch("strava_integration.admin.auto_rename_from_strava_data", side_effect=fake_rename) as rename_mock:
        auto_rename_activities(modeladmin, request, Activity.objects.filter(pk__in=[a1.pk, a2.pk]))

    assert rename_mock.call_count == 2
    # message_user called at least once (success path)
    assert modeladmin.message_user.called


@pytest.mark.django_db
def test_admin_action_reports_skipped_when_rename_returns_none(athlete):
    from unittest.mock import MagicMock
    from strava_integration.admin import auto_rename_activities
    from strava_integration.models import Activity
    from django.contrib import messages

    a1 = _make_activity(athlete, 72001, "Custom name (not generic)")

    modeladmin = MagicMock()
    request = MagicMock()

    with patch("strava_integration.admin.fetch_activity_detail", return_value={"id": 72001, "type": "Ride"}), \
         patch("strava_integration.admin.auto_rename_from_strava_data", return_value=None):
        auto_rename_activities(modeladmin, request, Activity.objects.filter(pk=a1.pk))

    # Verify a WARNING-level message was sent for the skipped activity
    calls = modeladmin.message_user.call_args_list
    levels = [c.kwargs.get("level") for c in calls]
    assert messages.WARNING in levels


@pytest.mark.django_db
def test_admin_action_continues_after_one_error(athlete):
    """If one activity errors, the others must still be processed."""
    from unittest.mock import MagicMock
    from strava_integration.admin import auto_rename_activities
    from strava_integration.models import Activity
    from django.contrib import messages

    a1 = _make_activity(athlete, 73001, "Morning Ride")
    a2 = _make_activity(athlete, 73002, "Evening Ride")

    def fake_fetch(sid):
        if sid == 73001:
            raise RuntimeError("boom")
        return {"id": sid, "type": "Ride"}

    modeladmin = MagicMock()
    request = MagicMock()

    with patch("strava_integration.admin.fetch_activity_detail", side_effect=fake_fetch), \
         patch("strava_integration.admin.auto_rename_from_strava_data", return_value="OK"):
        auto_rename_activities(modeladmin, request, Activity.objects.filter(pk__in=[a1.pk, a2.pk]))

    # Both an ERROR (for 73001) and a SUCCESS (for 73002) message should be sent
    calls = modeladmin.message_user.call_args_list
    levels = [c.kwargs.get("level") for c in calls]
    assert messages.ERROR in levels
    assert messages.SUCCESS in levels


@pytest.mark.django_db
def test_admin_action_empty_queryset_emits_no_messages(athlete):
    from unittest.mock import MagicMock
    from strava_integration.admin import auto_rename_activities
    from strava_integration.models import Activity

    modeladmin = MagicMock()
    request = MagicMock()

    with patch("strava_integration.admin.fetch_activity_detail") as fetch_mock, \
         patch("strava_integration.admin.auto_rename_from_strava_data") as rename_mock:
        auto_rename_activities(modeladmin, request, Activity.objects.none())

    fetch_mock.assert_not_called()
    rename_mock.assert_not_called()
    modeladmin.message_user.assert_not_called()


# ---------------------------------------------------------------------------
# Force admin action (with interstitial confirmation)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_force_admin_action_without_confirmation_renders_confirm_page(athlete):
    """First click on the force action: renders the confirmation page, does NOT rename."""
    from unittest.mock import MagicMock
    from strava_integration.admin import force_auto_rename_activities
    from strava_integration.models import Activity

    a = _make_activity(athlete, 74001, "My custom Garraf loop")

    modeladmin = MagicMock()
    modeladmin.model = Activity
    request = MagicMock()
    request.POST = {}  # no "post" key → confirmation page

    with patch("strava_integration.admin.fetch_activity_detail") as fetch_mock, \
         patch("strava_integration.admin.auto_rename_from_strava_data") as rename_mock:
        response = force_auto_rename_activities(modeladmin, request, Activity.objects.filter(pk=a.pk))

    fetch_mock.assert_not_called()
    rename_mock.assert_not_called()
    modeladmin.message_user.assert_not_called()
    # Returned an HttpResponse (rendered template)
    assert response is not None
    assert response.status_code == 200
    assert b"force-rename" in response.content.lower() or b"Force" in response.content


@pytest.mark.django_db
def test_force_admin_action_with_confirmation_renames(athlete):
    """When post=yes, the force action calls auto_rename_from_strava_data with force=True."""
    from unittest.mock import MagicMock
    from strava_integration.admin import force_auto_rename_activities
    from strava_integration.models import Activity

    a = _make_activity(athlete, 74002, "My custom name")

    modeladmin = MagicMock()
    request = MagicMock()
    request.POST = {"post": "yes"}

    with patch("strava_integration.admin.fetch_activity_detail",
               return_value={"id": 74002, "type": "Ride", "name": "My custom name"}), \
         patch("strava_integration.admin.auto_rename_from_strava_data",
               return_value="New name ~8km spacing") as rename_mock:
        force_auto_rename_activities(modeladmin, request, Activity.objects.filter(pk=a.pk))

    rename_mock.assert_called_once()
    # The force=True kwarg must have been passed
    assert rename_mock.call_args.kwargs.get("force") is True
    modeladmin.message_user.assert_called()


@pytest.mark.django_db
def test_webhook_create_does_not_block_on_thread(athlete):
    """
    The handler must return without waiting for the thread.
    We verify that Thread().start() is called (not Thread().run()) — start is
    asynchronous, run is synchronous — and that nothing is fetched or stored
    in the request itself.
    """
    client = Client()

    with patch("strava_integration.views.fetch_activity_detail") as fetch_mock, \
         patch("strava_integration.views.store_activity_from_strava_data") as store_mock, \
         patch("strava_integration.views.threading.Thread") as thread_cls:
        resp = _post_webhook(client, CREATE_EVENT)

    assert resp.status_code == 200
    thread_instance = thread_cls.return_value
    thread_instance.start.assert_called_once()
    thread_instance.run.assert_not_called()
    fetch_mock.assert_not_called()
    store_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Settings: IPv4-only outbound HTTP on Render
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("env, expected", [
    ({}, False),
    ({"RENDER": "true"}, True),
    ({"RENDER": ""}, False),
    ({"GEOCODING_FORCE_IPV4": "1"}, True),
    ({"GEOCODING_FORCE_IPV4": "true"}, True),
    ({"GEOCODING_FORCE_IPV4": "YES"}, True),
    ({"GEOCODING_FORCE_IPV4": " True "}, True),
    ({"GEOCODING_FORCE_IPV4": "0", "RENDER": "true"}, False),
    ({"GEOCODING_FORCE_IPV4": "false", "RENDER": "true"}, False),
    ({"GEOCODING_FORCE_IPV4": "No", "RENDER": "true"}, False),
    # Unrecognised value: fall back to the RENDER rule.
    ({"GEOCODING_FORCE_IPV4": "maybe", "RENDER": "true"}, True),
    ({"GEOCODING_FORCE_IPV4": "maybe"}, False),
    ({"GEOCODING_FORCE_IPV4": ""}, False),
])
def test_force_ipv4_outbound_truth_table(env, expected):
    from strava_app.settings import _force_ipv4_outbound

    assert _force_ipv4_outbound(env) is expected


@pytest.mark.parametrize("override, expect_ipv6_disabled", [("1", True), ("0", False)])
def test_settings_import_applies_ipv4_preference(override, expect_ipv6_disabled):
    """Wiring check in a fresh interpreter: importing the settings flips
    urllib3's HAS_IPV6 only when _force_ipv4_outbound(os.environ) is True."""
    import os
    import subprocess
    import sys
    from django.conf import settings

    script = (
        "import urllib3.util.connection as c\n"
        "before = c.HAS_IPV6\n"
        "import strava_app.settings\n"
        "print(before, c.HAS_IPV6)\n"
    )
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SECRET_KEY": "test-only",
        "RENDER": "true",
        "GEOCODING_FORCE_IPV4": override,
    }
    out = subprocess.run(
        [sys.executable, "-c", script],
        cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=60,
        check=True,
    ).stdout.split()
    before, after = out[-2:]
    if expect_ipv6_disabled:
        assert after == "False"
    else:
        assert after == before
