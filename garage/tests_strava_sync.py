"""«Sincronizar ahora», resumable Strava history and webhook hints (garage-030)."""
from datetime import timedelta
import json
from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.db.models import F
from django.test import Client
from django.utils import timezone

from .models import ActivitySource, ImportRun, Ride, StravaAccount, StravaEvent
from .services.strava_client import StravaClient
from .services.strava_sync import (PENDING_CAP, EventsResult, _process_in_thread, accept_event, cancel_strava_import, default_after,
                                   process_pending_events, purge_events, resume_strava_import, start_strava_import, sync_now)
from .tests_strava_client import ATHLETE, FakeResponse, at, connected, strava  # noqa: F401 (fixture)

WEBHOOK_URL = "/archive/strava/webhook/strava/"


@pytest.fixture
def small_pages():
    with patch("garage.services.strava_client.PER_PAGE", 2):
        yield 2


def ago(days, minutes=0):
    return (timezone.now() - timedelta(days=days, minutes=minutes)).replace(microsecond=0)


def strava_rows():
    return ActivitySource.objects.filter(source_kind="strava")


# «Sincronizar ahora» ---------------------------------------------------------

@pytest.mark.django_db
def test_sync_now_reads_seven_days_gear_and_pending_hints(strava):
    strava.fake.add(1, start=ago(2), gear="b1")
    strava.fake.add(2, start=ago(3), sport="Run")
    strava.fake.add(3, start=ago(30))  # outside the window: never asked
    with strava.fake.serving():
        result = sync_now(strava.owner)
    assert (result.imported, result.updated, result.skipped, result.error) == (1, 0, 1, "")
    account = StravaAccount.objects.get(owner=strava.owner)
    assert account.athlete_id == ATHLETE and account.last_sync_status == "ok" and account.last_error_code == ""
    assert set(strava_rows().values_list("external_id", flat=True)) == {1}
    window = next(call for call in strava.fake.calls if call.path == "/athlete/activities")
    assert abs(window.params["after"] - (timezone.now() - timedelta(days=7)).timestamp()) < 60
    # A second sync: already known, nothing duplicated; a pending create hint is confirmed through the API.
    strava.fake.add(4, start=ago(40))
    StravaEvent.objects.create(subscription_id=1, athlete_id=ATHLETE, object_type="activity", aspect_type="create", object_id=4,
                               event_time=at())
    with strava.fake.serving():
        result = sync_now(strava.owner)
    assert (result.imported, result.updated, result.events) == (0, 1, 1)
    assert set(strava_rows().values_list("external_id", flat=True)) == {1, 4} and Ride.objects.count() == 2
    assert StravaEvent.objects.get().processed_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize("response,code", [(FakeResponse(401), "unauthorized"),
                                           (FakeResponse(429, "{}", {"X-RateLimit-Usage": "600,30000"}), "rate_limited")])
def test_sync_failures_are_recorded_and_stop(strava, response, code):
    connected(strava)
    strava.fake.add(1, start=ago(1))
    strava.fake.script("/athlete/activities", response, response)
    with strava.fake.serving():
        result = sync_now(strava.owner)
    account = StravaAccount.objects.get()
    assert result.error == code and account.last_error_code == code and account.last_sync_status == "failed"
    assert not strava_rows().exists()
    assert strava.fake.paths().count("/athlete/activities") == (2 if code == "unauthorized" else 1), "no retry loops"


@pytest.mark.django_db
def test_sync_by_another_user_never_calls_strava(strava):
    with strava.fake.serving():
        assert sync_now(strava.other).error == "not_configured"
    assert not strava.fake.calls and not StravaAccount.objects.exists()


@pytest.mark.django_db
def test_old_events_are_purged(strava):
    old = StravaEvent.objects.create(subscription_id=1, athlete_id=ATHLETE, object_type="activity", aspect_type="create",
                                     object_id=1, event_time=at())
    StravaEvent.objects.filter(pk=old.pk).update(received_at=timezone.now() - timedelta(days=31))
    StravaEvent.objects.create(subscription_id=1, athlete_id=ATHLETE, object_type="activity", aspect_type="create", object_id=2,
                               event_time=at())
    assert purge_events() == 1 and StravaEvent.objects.get().object_id == 2


# Resumable history -----------------------------------------------------------

@pytest.mark.django_db
def test_history_pages_resume_and_complete(strava, small_pages):
    for key in range(1, 6):
        strava.fake.add(key, start=at(key), sport="Run" if key == 3 else "Ride")
    with strava.fake.serving():
        run = start_strava_import(strava.owner, after=at(1) - timedelta(days=1))
    assert (run.source_kind, run.state, run.processed, run.cursor, run.total) == ("strava", "paused", 1, 1, None)
    assert (run.items_imported, run.items_skipped, run.file_hash, run.session_indices) == (2, 0, "", [])
    with strava.fake.serving():
        run = resume_strava_import(strava.owner, run.pk, budget=5)
    assert (run.state, run.processed, run.cursor, run.items_imported, run.items_skipped) == ("completed", 3, 3, 4, 1)
    assert set(strava_rows().values_list("import_run_id", flat=True)) == {run.pk}
    pages = [call.params["page"] for call in strava.fake.calls if call.path == "/athlete/activities"]
    assert pages == [1, 2, 3] and {call.params["after"] for call in strava.fake.calls if call.params} == {int((at(1) - timedelta(days=1)).timestamp())}
    with strava.fake.serving():
        assert resume_strava_import(strava.owner, run.pk).state == "completed"
    assert pages == [call.params["page"] for call in strava.fake.calls if call.path == "/athlete/activities"]


@pytest.mark.django_db
def test_history_ends_on_an_empty_page(strava, small_pages):
    for key in range(1, 5):
        strava.fake.add(key, start=at(key))
    with strava.fake.serving():
        run = start_strava_import(strava.owner, after=at(1) - timedelta(days=1), budget=5)
    assert (run.state, run.processed, run.cursor, run.items_imported) == ("completed", 2, 2, 4)


@pytest.mark.django_db
def test_rate_limit_keeps_the_cursor_and_resumes(strava, small_pages):
    for key in range(1, 5):
        strava.fake.add(key, start=at(key))
    strava.fake.script("/athlete/activities", FakeResponse(200, "[" + strava.fake.texts[1] + ", " + strava.fake.texts[2] + "]"),
                       FakeResponse(429, "{}", {"X-RateLimit-Usage": "100,900"}))
    with strava.fake.serving():
        run = start_strava_import(strava.owner, after=at(1) - timedelta(days=1), budget=3)
    assert (run.state, run.cursor, run.processed, run.errors) == ("failed", 1, 1, [{"code": "rate_limited", "session_index": None}])
    assert StravaAccount.objects.get().last_error_code == "rate_limited" and strava_rows().count() == 2
    with strava.fake.serving():
        run = resume_strava_import(strava.owner, run.pk, budget=3)
    # Page 2 is full, page 3 is empty: two confirmed pages.
    assert (run.state, run.cursor, run.processed, run.items_imported, run.errors) == ("completed", 2, 2, 4, [])
    assert strava_rows().count() == 4 and Ride.objects.count() == 4


@pytest.mark.django_db
def test_cancel_and_foreign_runs(strava, small_pages):
    for key in range(1, 6):
        strava.fake.add(key, start=at(key))
    with strava.fake.serving():
        run = start_strava_import(strava.owner, after=at(1) - timedelta(days=1))
    run = cancel_strava_import(strava.owner, run.pk)
    calls = len(strava.fake.calls)
    with strava.fake.serving():
        assert resume_strava_import(strava.owner, run.pk).state == "cancelled"
    assert len(strava.fake.calls) == calls and strava_rows().count() == 2
    from .services.ownership import InventoryNotFound
    with pytest.raises(InventoryNotFound):
        resume_strava_import(strava.other, run.pk)


@pytest.mark.django_db
def test_a_step_never_redoes_a_page_another_request_confirmed(strava, small_pages):
    for key in range(1, 4):
        strava.fake.add(key, start=at(key))
    with strava.fake.serving():
        run = start_strava_import(strava.owner, after=at(1) - timedelta(days=1))
    original = strava.fake.get

    def concurrent(url, **kwargs):
        ImportRun.objects.filter(pk=run.pk).update(cursor=F("cursor") + 1, processed=F("processed") + 1)
        return original(url, **kwargs)
    with patch("garage.services.strava_client.requests.get", side_effect=concurrent), \
         patch("garage.services.strava_client.refresh_access_token", return_value="synthetic"):
        after = resume_strava_import(strava.owner, run.pk)
    assert after.cursor == 2 and strava_rows().count() == 2, "page 2 was not stored twice"


@pytest.mark.django_db
def test_import_validation_and_default_date(strava):
    from django.core.exceptions import ValidationError
    with strava.fake.serving():
        for value in (timezone.now() + timedelta(days=1), "2026-01-01"):
            with pytest.raises(ValidationError):
                start_strava_import(strava.owner, after=value)
        with pytest.raises(ValidationError):
            start_strava_import(strava.owner, after=at(), budget=6)
    assert not ImportRun.objects.exists() and not strava.fake.calls
    assert default_after(strava.owner).date().isoformat() == f"{timezone.now().year - 1}-01-01"
    from .services.rides import create_manual_ride
    create_manual_ride(strava.owner, started_at=at(4))
    assert default_after(strava.owner) == at(4)


@pytest.mark.django_db
def test_strava_run_constraints(strava):
    run = ImportRun.objects.create(owner=strava.owner, source_kind="strava", items_imported=0, items_skipped=0)
    for changes in ({"total": 1}, {"file_hash": "a" * 64}):
        with pytest.raises(IntegrityError), transaction.atomic():
            ImportRun.objects.filter(pk=run.pk).update(**changes)
    assert str(run).startswith("Strava import")


# Webhook hints -----------------------------------------------------------------

def event(object_id=7, aspect="create", owner=ATHLETE, **extra):
    return {"object_type": "activity", "aspect_type": aspect, "object_id": object_id, "owner_id": owner,
            "subscription_id": 120, "event_time": 1767261600, "updates": {}, **extra}


def post(payload):
    return Client().post(WEBHOOK_URL, data=json.dumps(payload), content_type="application/json")


@pytest.mark.django_db
def test_unknown_athletes_are_dropped_and_not_stored(strava):
    from strava_integration.models import Activity
    with patch("garage.services.strava_sync.threading.Thread") as thread, \
         patch("garage.services.strava_client.requests.get") as get:
        assert post(event()).status_code == 200
    assert not StravaEvent.objects.exists() and not Activity.objects.exists()
    thread.assert_not_called()
    get.assert_not_called()


@pytest.mark.django_db
def test_hint_is_stored_before_200_and_strava_is_not_called_in_the_request(strava, django_capture_on_commit_callbacks):
    connected(strava)
    with patch("garage.services.strava_sync.threading.Thread") as thread, \
         patch("garage.services.strava_client.requests.get") as get, \
         patch("garage.services.strava_client.refresh_access_token") as token, \
         django_capture_on_commit_callbacks(execute=True) as callbacks:
        response = post(event(updates={"title": "Mi vuelta privada", "type": "Ride", "private": True}))
    assert response.status_code == 200
    stored = StravaEvent.objects.get()
    assert (stored.athlete_id, stored.object_id, stored.aspect_type, stored.processed_at) == (ATHLETE, 7, "create", None)
    assert stored.updates == {"type": "Ride", "private": "True"}, "no titles are kept"
    get.assert_not_called()
    token.assert_not_called()
    kwargs = thread.call_args.kwargs
    assert len(callbacks) == 1, "the worker starts only after the hint is committed"
    assert kwargs["target"] is _process_in_thread and kwargs["args"][0] == ATHLETE and kwargs["daemon"] is True
    thread.return_value.start.assert_called_once()


@pytest.mark.django_db
def test_dedupe_cap_subscription_and_athlete_events(strava, settings, django_capture_on_commit_callbacks):
    connected(strava)
    with patch("garage.services.strava_sync.threading.Thread") as thread, django_capture_on_commit_callbacks(execute=True):
        assert accept_event(event()) and not accept_event(event()), "Strava retries are deduplicated"
        assert not accept_event({**event(), "object_type": "athlete", "updates": {"authorized": "false"}}), "ignored in token mode"
        for broken in (event(object_id="7"), event(owner=True), {**event(), "aspect_type": "rename"}, [], None):
            assert not accept_event(broken)
        settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID = "999"
        assert not accept_event(event(object_id=8))
        settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID = "120"
        assert accept_event(event(object_id=8))
        settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID = "garbage"
        assert not accept_event(event(object_id=9))
        settings.STRAVA_WEBHOOK_SUBSCRIPTION_ID = ""
        StravaEvent.objects.bulk_create([StravaEvent(subscription_id=120, athlete_id=ATHLETE, object_type="activity", aspect_type="update",
                                                     object_id=1000 + key, event_time=at()) for key in range(PENDING_CAP - 2)])
        assert not accept_event(event(object_id=10)), "at most 500 pending hints per athlete"
    # Two hints accepted, but this process starts one worker for the athlete (the second only asks for another round).
    assert thread.call_count == 1 and StravaEvent.objects.count() == PENDING_CAP


@pytest.mark.django_db
def test_the_worker_closes_its_connection_and_releases_the_athlete(strava):
    from .services import strava_sync
    token = strava_sync._enter(ATHLETE)
    with patch("garage.services.strava_sync.connection") as connection, \
         patch("garage.services.strava_sync.process_pending_events", side_effect=RuntimeError("boom")):
        _process_in_thread(ATHLETE, token)
    connection.close.assert_called_once()
    assert ATHLETE not in strava_sync._workers


@pytest.mark.django_db
def test_legacy_and_garage_both_receive_the_owner_athlete(strava, django_capture_on_commit_callbacks):
    from strava_integration.models import Athlete
    connected(strava)
    Athlete.objects.create(strava_id=ATHLETE, first_name="Ana")
    from strava_integration.views import _safe_auto_rename
    # Both modules use the same threading.Thread: one patch sees the legacy rename and the Garage worker.
    with patch("threading.Thread") as thread, \
         patch("strava_integration.views.fetch_activity_detail", return_value={"id": 7, "type": "Ride"}) as fetch, \
         patch("strava_integration.views.store_activity_from_strava_data") as store, \
         django_capture_on_commit_callbacks(execute=True):
        assert post(event()).status_code == 200
    fetch.assert_called_once_with(7)
    store.assert_called_once()
    # Outside a test transaction the Garage worker starts at once; here on_commit runs it after the legacy rename.
    assert sorted(call.kwargs["target"].__name__ for call in thread.call_args_list) == ["_process_in_thread", "_safe_auto_rename"]
    assert StravaEvent.objects.count() == 1


def hint(object_id, aspect):
    return StravaEvent.objects.create(subscription_id=120, athlete_id=ATHLETE, object_type="activity", aspect_type=aspect,
                                      object_id=object_id, event_time=at(object_id % 28 + 1))


@pytest.mark.django_db
def test_create_update_and_forged_or_real_deletes(strava):
    connected(strava)
    strava.fake.add(7, start=at(5), name="Primera")
    hint(7, "create")
    with strava.fake.serving():
        assert process_pending_events(ATHLETE, client=StravaClient()).settled == 1
    ride = strava_rows().get(external_id=7).ride
    strava.fake.add(7, start=at(5), name="Renombrada")
    hint(7, "update")
    forged = hint(7, "delete")  # unsigned hint: the activity is still on Strava
    with strava.fake.serving():
        assert process_pending_events(ATHLETE, client=StravaClient()).settled == 2
    ride.refresh_from_db()
    assert ride.name == "Renombrada" and strava_rows().filter(external_id=7).exists()
    forged.refresh_from_db()
    assert forged.processed_at is not None and forged.error_code == ""
    strava.fake.delete(7)
    StravaEvent.objects.filter(pk=forged.pk).update(processed_at=None)
    with strava.fake.serving():
        assert process_pending_events(ATHLETE, client=StravaClient()).settled == 1
    assert not strava_rows().exists() and not Ride.objects.filter(pk=ride.pk).exists(), "a confirmed delete withdraws the Strava data"
    assert "/activities/7" in strava.fake.paths()


@pytest.mark.django_db
def test_rate_limited_hints_stay_pending(strava):
    connected(strava)
    first, second = hint(1, "create"), hint(2, "create")
    strava.fake.script("/activities/1", FakeResponse(429))
    with strava.fake.serving():
        assert process_pending_events(ATHLETE, client=StravaClient()) == EventsResult(0, "rate_limited")
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.processed_at is None and first.error_code == "rate_limited" and first.attempts == 1
    assert second.processed_at is None and second.attempts == 0, "the batch stops at a 429"
    with strava.fake.serving():  # gone (or private) now: settled without storing anything
        assert process_pending_events(ATHLETE, client=StravaClient()) == EventsResult(2)
    first.refresh_from_db()
    assert first.error_code == "not_found" and not strava_rows().exists()


@pytest.mark.django_db
def test_hints_without_an_account_do_nothing(strava):
    hint(1, "delete")
    with strava.fake.serving():
        assert process_pending_events(ATHLETE) == EventsResult()
    assert not strava.fake.calls


# Review of phases 1–2 (18 oct) -----------------------------------------------------

def test_production_settings_read_both_garage_strava_variables():
    """strava_app/settings.py refuses to import under pytest, so its assignments are read as code."""
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).resolve().parent.parent / "strava_app" / "settings.py").read_text())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = node.value
            if (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr in ("getenv", "get")
                    and [ast.literal_eval(arg) for arg in value.args] == [node.targets[0].id, ""]):
                found[node.targets[0].id] = True
    assert {"GARAGE_STRAVA_USER", "STRAVA_WEBHOOK_SUBSCRIPTION_ID"} <= set(found), "read from the environment, empty by default"


def page_rows(start_id, count, *, start, gear="b1"):
    from decimal import Decimal
    from .tests_strava_client import activity_text
    return [json.loads(activity_text(start_id + key, start=start + timedelta(hours=3 * key), gear=gear), parse_float=Decimal)
            for key in range(count)]


@pytest.mark.django_db
@pytest.mark.parametrize("case", ["new", "joins_fit", "unchanged"])
def test_query_budget_per_activity_for_a_page_of_twenty(strava, case):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    from .models import Bike, Category, Item, StravaGear
    from .services.ownership import _lock_owner, create_inventory
    from .services.rides import import_fit_session
    from .services.strava_sources import link_gear
    from .services.strava_sync import _store_rows
    from .services.usage_profiles import create_profile_history
    account = connected(strava)
    bike = create_inventory(strava.owner, Bike, name="Gravel")
    link_gear(strava.owner, StravaGear.objects.get(gear_id="b1").pk, bike)
    helmet = create_inventory(strava.owner, Item, name="Casco", category=create_inventory(strava.owner, Category, name="Equipación"))
    create_profile_history(strava.owner, items=[helmet], started_at=at(1) - timedelta(days=30), name="Ciclismo", sport_type="cycling")
    rows = page_rows(500, 20, start=at(2))
    if case == "joins_fit":
        for key in range(20):
            import_fit_session(strava.owner, file_hash=f"{key + 1:064x}", session_index=0, parser_version="fixture-1",
                               observations={"started_at": at(2) + timedelta(hours=3 * key), "sport_type": "cycling",
                                             "distance_m": 30000})
    if case == "unchanged":
        with transaction.atomic():
            _store_rows(_lock_owner(strava.owner), account, rows)
    with CaptureQueriesContext(connection) as queries, transaction.atomic():
        result = _store_rows(_lock_owner(strava.owner), account, rows)
    per_activity = len(queries) / 20
    budget = 4 if case == "unchanged" else 15  # was ≈ 82 per new activity before the review
    assert per_activity <= budget, (case, len(queries))
    assert (result.imported if case != "unchanged" else result.unchanged) == 20
    assert set(ItemUsage_rides(helmet)) == set(ActivitySource.objects.filter(source_kind="strava").values_list("ride_id", flat=True))


def ItemUsage_rides(item):
    from .models import ItemUsage
    return ItemUsage.objects.filter(item=item).values_list("ride_id", flat=True)


@pytest.mark.django_db
def test_sync_now_bounds_its_strava_calls(strava, small_pages):
    from .services.strava_sync import SYNC_EVENTS, SYNC_MAX_CALLS
    connected(strava)
    for key in range(1, 7):  # three pages of two: more than SYNC_MAX_PAGES
        strava.fake.add(key, start=ago(1, minutes=10 * key))
    for key in range(SYNC_EVENTS + 2):
        strava.fake.add(100 + key, start=ago(20))
        hint(100 + key, "create")
    calls = len(strava.fake.calls)
    with strava.fake.serving():
        result = sync_now(strava.owner)
    made = len(strava.fake.calls) - calls
    assert made + strava.fake.tokens - 1 <= SYNC_MAX_CALLS and made == 1 + 2 + SYNC_EVENTS, made
    assert (result.events, result.pending, result.complete, result.error) == (SYNC_EVENTS, 2, False, "")


@pytest.mark.django_db
def test_sync_now_starts_no_call_after_its_time_limit(strava, small_pages):
    connected(strava)
    for key in range(1, 5):
        strava.fake.add(key, start=ago(1, minutes=key))
    hint(50, "create")
    with strava.fake.serving(), patch("garage.services.strava_sync.REQUEST_SECONDS", 0):
        result = sync_now(strava.owner)
    assert strava.fake.paths()[-1] == "/athlete/activities" and strava.fake.paths().count("/athlete/activities") == 1
    assert (result.imported, result.events, result.pending, result.complete) == (2, 0, 1, False)


@pytest.mark.django_db
@pytest.mark.parametrize("response,code", [(FakeResponse(429, "{}", {"X-RateLimit-Usage": "600,30000"}), "rate_limited"),
                                           (FakeResponse(401), "unauthorized")])
def test_a_stop_code_from_the_hints_fails_the_sync(strava, response, code):
    connected(strava)
    hint(60, "create")
    strava.fake.script("/activities/60", response, response)
    with strava.fake.serving():
        result = sync_now(strava.owner)
    account = StravaAccount.objects.get()
    assert result.error == code and (account.last_sync_status, account.last_error_code) == ("failed", code)
    assert result.pending == 1


@pytest.mark.django_db
def test_unusable_responses_stop_retrying_after_max_attempts(strava):
    from .services.strava_sync import MAX_ATTEMPTS
    connected(strava)
    stuck = hint(70, "create")
    for attempt in range(1, MAX_ATTEMPTS + 1):
        strava.fake.script("/activities/70", FakeResponse(200, "[]"))  # not an activity: invalid_response
        with strava.fake.serving():
            result = process_pending_events(ATHLETE, client=StravaClient())
        stuck.refresh_from_db()
        assert stuck.attempts == attempt and stuck.error_code == "invalid_response"
        assert (stuck.processed_at is None) is (attempt < MAX_ATTEMPTS) and result.settled == (attempt == MAX_ATTEMPTS)
    assert not StravaEvent.objects.filter(processed_at__isnull=True).exists(), "no longer counts toward the pending cap"


@pytest.mark.django_db
def test_a_404_without_read_all_never_deletes(strava):
    from types import SimpleNamespace
    from .tests_strava_sources import store as store_source
    account = connected(strava)
    StravaAccount.objects.filter(pk=account.pk).update(scopes="read")
    store_source(SimpleNamespace(owner=strava.owner, account=StravaAccount.objects.get()), 80, start=at(9))
    strava.fake.delete(80)  # now answers 404, which without activity:read_all may only mean «private»
    deleted = hint(80, "delete")
    calls = len(strava.fake.calls)
    with strava.fake.serving():
        assert process_pending_events(ATHLETE, client=StravaClient()).settled == 1
    deleted.refresh_from_db()
    assert strava_rows().filter(external_id=80).exists() and deleted.processed_at is not None
    assert len(strava.fake.calls) == calls, "nothing to confirm: Strava is not even asked"


@pytest.mark.django_db
@pytest.mark.parametrize("athlete", [None, ATHLETE + 1])
def test_a_hinted_activity_must_name_this_athlete(strava, athlete, caplog):
    connected(strava)
    from .tests_strava_client import activity_text
    text = activity_text(90, start=at(10), athlete=athlete or ATHLETE)
    if athlete is None:
        text = text.replace('"athlete": {"id": %d}, ' % ATHLETE, "")
    strava.fake.script("/activities/90", FakeResponse(200, text))
    event = hint(90, "create")
    with strava.fake.serving():
        assert process_pending_events(ATHLETE, client=StravaClient()).settled == 1
    event.refresh_from_db()
    assert event.error_code == "invalid_response" and not strava_rows().exists()
    assert "Garage Strava activity skipped: athlete." in caplog.text and "Vuelta" not in caplog.text


@pytest.mark.django_db
def test_run_errors_accumulate_across_pages(strava, small_pages):
    from .tests_strava_client import activity_text
    valid = [activity_text(key, start=at(key)) for key in range(1, 5)]
    broken = activity_text(9, start=at(1)).replace('"start_date": "2026-03-01T10:00:00Z"', '"start_date": null')
    strava.fake.script("/athlete/activities", FakeResponse(200, f"[{valid[0]}, {broken}]"), FakeResponse(200, f"[{valid[1]}, {valid[2]}]"),
                       FakeResponse(429, "{}"), FakeResponse(200, f"[{valid[3]}]"))
    with strava.fake.serving():
        run = start_strava_import(strava.owner, after=at(1) - timedelta(days=1), budget=3)
    invalid, limited = {"code": "invalid_metric", "session_index": None}, {"code": "rate_limited", "session_index": None}
    assert (run.state, run.cursor, run.errors) == ("failed", 2, [invalid, limited]), "page 1's summary survives page 2"
    with strava.fake.serving():
        run = resume_strava_import(strava.owner, run.pk, budget=3)
    assert (run.state, run.cursor, run.errors, run.items_imported, run.items_skipped) == ("completed", 3, [invalid], 4, 1)


@pytest.mark.django_db
def test_one_worker_per_athlete_and_one_more_round_for_late_hints(strava):
    from .services import strava_sync
    connected(strava)
    strava.fake.add(1, start=at(11))
    strava.fake.add(2, start=at(12))
    hint(1, "create")
    with patch("garage.services.strava_sync.threading.Thread") as thread:
        assert strava_sync._start_worker(ATHLETE) and not strava_sync._start_worker(ATHLETE)
        assert thread.call_count == 1, "a second hint asks the running worker for one more round"
        assert process_pending_events(ATHLETE).busy, "sync_now never runs a second worker either"
    original = strava.fake.get

    def late_hint(url, **kwargs):
        if url.endswith("/activities/1"):
            hint(2, "create")
            assert not strava_sync._start_worker(ATHLETE)  # what the webhook's on_commit does meanwhile
        return original(url, **kwargs)
    kwargs = thread.call_args.kwargs
    with patch("garage.services.strava_client.requests.get", side_effect=late_hint), \
         patch("garage.services.strava_client.refresh_access_token", return_value="synthetic"), \
         patch("garage.services.strava_sync.connection"):
        kwargs["target"](*kwargs["args"])
    assert set(strava_rows().values_list("external_id", flat=True)) == {1, 2}, "the late hint was confirmed in a second round"
    assert not StravaEvent.objects.filter(processed_at__isnull=True).exists() and ATHLETE not in strava_sync._workers


@pytest.mark.django_db(transaction=True)
def test_no_strava_call_runs_inside_a_transaction(strava, small_pages):
    from django.db import connection
    connected(strava)
    for key in range(1, 4):
        strava.fake.add(key, start=ago(1, minutes=key))
    strava.fake.add(9, start=ago(2))
    hint(9, "create")
    hint(3, "delete")
    seen = []
    original_get, original_token = strava.fake.get, strava.fake.token

    def get(url, **kwargs):
        seen.append(connection.in_atomic_block)
        return original_get(url, **kwargs)

    def token():
        seen.append(connection.in_atomic_block)
        return original_token()
    with patch("garage.services.strava_client.requests.get", side_effect=get), \
         patch("garage.services.strava_client.refresh_access_token", side_effect=token):
        assert sync_now(strava.owner).error == ""
        run = start_strava_import(strava.owner, after=ago(5), budget=3)
        StravaEvent.objects.create(subscription_id=120, athlete_id=ATHLETE, object_type="activity", aspect_type="update",
                                   object_id=2, event_time=at(3))
        assert process_pending_events(ATHLETE).settled == 1
    assert run.state == "completed" and len(seen) > 8 and not any(seen), seen


@pytest.mark.django_db(transaction=True)
def test_removing_strava_data_never_waits_for_a_hint_in_flight(strava):
    """Lock order: a hint's Strava call holds no lock; its write takes the owner lock before the event row."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import close_old_connections
    from .services.strava_sources import remove_strava_data
    connected(strava)
    strava.fake.add(7, start=at(5))
    hint(7, "create")
    in_call, removed = Event(), Event()
    original = strava.fake.get

    def slow(url, **kwargs):
        if url.endswith("/activities/7"):
            in_call.set()
            assert removed.wait(timeout=10), "«Quitar lo sincronizado» waited for a hint in flight"
        return original(url, **kwargs)

    def remove():
        close_old_connections()
        try:
            assert in_call.wait(timeout=10)
            remove_strava_data(strava.owner)
            removed.set()
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=1) as pool, \
         patch("garage.services.strava_client.requests.get", side_effect=slow), \
         patch("garage.services.strava_client.refresh_access_token", return_value="synthetic"):
        future = pool.submit(remove)
        result = process_pending_events(ATHLETE, client=StravaClient())
        future.result(timeout=20)
    assert result.error == "" and removed.is_set()
    assert not StravaAccount.objects.exists() and not StravaEvent.objects.exists() and not strava_rows().exists(), \
        "the hint found the account gone under the owner lock and stored nothing"
