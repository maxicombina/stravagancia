"""Strava phase 4 «operación diaria» (garage-030): sync-all endpoint, sync_all, absence hints, revocation and commands.

Strava is simulated as in tests_strava_client (JSON text answered to a mocked
requests.get): no real HTTP, the test bootstrap blocks sockets as well.
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
import json
import logging
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .models import ActivitySource, Ride, StravaAccount, StravaEvent, StravaGear
from .services import strava_sync
from .services.rides import correct_ride, withdraw_source
from .services.strava_sync import PENDING_CAP, SyncAllResult, accept_event, sync_all, sync_now
from .tests_strava_client import ATHLETE, FakeResponse, activity_text, at, connected, strava  # noqa: F401 (fixture)
from .tests_strava_sources import fit, store
from .tests_strava_sync import ago, hint, small_pages, strava_rows  # noqa: F401 (fixture)

TOKEN = "synthetic-sync-token-0123456789-abcdefghij"  # 42 characters, never a real secret
URL = "/garage/strava/sync-all/"


def writes(queries):
    return [q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}]


def absence_hints():
    return StravaEvent.objects.filter(updates__origin="absence")


def call(client=None, token=TOKEN, method="post", **extra):
    headers = {} if token is None else {"HTTP_X_SYNC_TOKEN": token}
    return getattr(client or Client(), method)(URL, **headers, **extra)


def old_event():
    """A hint received 31 days ago: sync_all purges it."""
    event = StravaEvent.objects.create(subscription_id=1, athlete_id=ATHLETE, object_type="activity", aspect_type="create",
                                       object_id=999, event_time=at())
    StravaEvent.objects.filter(pk=event.pk).update(received_at=timezone.now() - timedelta(days=31))
    return event


def synced(strava, *activities):
    """The account plus these {id: start} activities stored by one button press."""
    connected(strava)
    for activity_id, start in activities:
        strava.fake.add(activity_id, start=start)
    with strava.fake.serving():
        assert sync_now(strava.owner).error == ""
    return StravaAccount.objects.get()


# Endpoint --------------------------------------------------------------------

def test_the_endpoint_is_named_and_the_setting_comes_from_the_environment():
    import ast
    assert reverse("garage:strava-sync-all") == URL
    tree = ast.parse((Path(__file__).resolve().parent.parent / "strava_app" / "settings.py").read_text())
    found = [node for node in tree.body if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "GARAGE_SYNC_TOKEN"]
    assert len(found) == 1 and ast.unparse(found[0].value) == "os.getenv('GARAGE_SYNC_TOKEN', '')"
    from django.conf import settings
    assert settings.GARAGE_SYNC_TOKEN == "", "settings_test leaves the daily sync disabled"


@pytest.mark.django_db
@pytest.mark.parametrize("configured", ["", "x" * 31, None])
@pytest.mark.parametrize("method", ["post", "get"])
def test_without_a_long_enough_token_the_endpoint_does_not_exist(strava, configured, method):
    synced(strava, (1, ago(1)))
    old = old_event()
    with override_settings(GARAGE_SYNC_TOKEN=configured), strava.fake.serving(), \
         CaptureQueriesContext(connection) as queries:
        calls = len(strava.fake.calls)
        response = call(token=configured or TOKEN, method=method)
    assert response.status_code == 404
    assert not writes(queries) and len(strava.fake.calls) == calls and StravaEvent.objects.filter(pk=old.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("given", [None, "", "wrong", TOKEN[:-1], TOKEN + "x", TOKEN.upper(), "señal-" + TOKEN])
def test_a_missing_or_different_token_is_a_bare_403_that_writes_nothing(strava, given):
    synced(strava, (1, ago(1)))
    old = old_event()
    pending = hint(7, "create")
    with override_settings(GARAGE_SYNC_TOKEN=TOKEN), strava.fake.serving(), CaptureQueriesContext(connection) as queries:
        calls = len(strava.fake.calls)
        response = call(token=given)
    assert response.status_code == 403 and response.content == b"", "no text that helps guessing"
    assert not writes(queries) and len(strava.fake.calls) == calls
    assert StravaEvent.objects.filter(pk=old.pk).exists() and StravaEvent.objects.get(pk=pending.pk).attempts == 0


@pytest.mark.django_db
def test_the_right_token_runs_the_daily_sync_without_session_or_csrf(strava):
    synced(strava, (1, ago(1)))
    strava.fake.add(2, start=ago(2))
    with override_settings(GARAGE_SYNC_TOKEN=TOKEN), strava.fake.serving():
        response = call(Client(enforce_csrf_checks=True), data="ignored body", content_type="text/plain")
    assert response.status_code == 200 and response["Content-Type"] == "application/json"
    assert json.loads(response.content) == {"pending": 0, "status": "ok", "error": "", "accounts": 1, "purged": 0, "absences": 0}
    assert set(strava_rows().values_list("external_id", flat=True)) == {1, 2}
    with override_settings(GARAGE_SYNC_TOKEN=TOKEN):
        assert call(method="get").status_code == 405, "POST only"
        assert call(method="put").status_code == 405


@pytest.mark.django_db
def test_a_session_is_no_substitute_for_the_token(strava, client):
    synced(strava, (1, ago(1)))
    client.force_login(strava.owner)
    with override_settings(GARAGE_SYNC_TOKEN=TOKEN), strava.fake.serving():
        calls = len(strava.fake.calls)
        assert call(client, token=None).status_code == 403
    assert len(strava.fake.calls) == calls


@pytest.mark.django_db
def test_a_failed_run_still_answers_200_with_its_code(strava):
    synced(strava, (1, ago(1)))
    strava.fake.script("/athlete", FakeResponse(429, "{}", {"X-RateLimit-Usage": "600,30000"}))
    with override_settings(GARAGE_SYNC_TOKEN=TOKEN), strava.fake.serving():
        response = call()
    assert response.status_code == 200
    assert json.loads(response.content) == {"pending": 0, "status": "failed", "error": "rate_limited", "accounts": 1,
                                            "purged": 0, "absences": 0}


@pytest.mark.django_db
def test_the_token_never_reaches_logs_or_responses(strava, caplog):
    synced(strava, (1, ago(1)))
    caplog.set_level(logging.DEBUG)
    responses = []
    with override_settings(GARAGE_SYNC_TOKEN=TOKEN), strava.fake.serving():
        for given in (None, "wrong", TOKEN[:-1], TOKEN):
            responses.append(call(token=given))
    with override_settings(GARAGE_SYNC_TOKEN=TOKEN[:31]):
        responses.append(call(token=TOKEN[:31]))
    assert [response.status_code for response in responses] == [403, 403, 403, 200, 404]
    for response in responses:
        assert TOKEN[:31] not in response.content.decode() and TOKEN[:31] not in str(response.headers)
    assert TOKEN[:31] not in caplog.text and "Garage Strava daily sync" in caplog.text


@pytest.mark.django_db
def test_a_crash_with_debug_never_shows_the_token(strava, settings):
    """Review of phase 4: Django's DEBUG 500 page cleanses META and settings, but prints frame locals unfiltered."""
    synced(strava, (1, ago(1)))
    settings.DEBUG = True
    with override_settings(GARAGE_SYNC_TOKEN=TOKEN), patch("garage.strava_views.run_sync_all", side_effect=RuntimeError("boom")):
        response = Client(raise_request_exception=False).post(URL, HTTP_X_SYNC_TOKEN=TOKEN)
    page = response.content.decode()
    assert response.status_code == 500 and "RuntimeError" in page and "Local vars" in page, "the technical page"
    assert TOKEN[:31] not in page


# sync_all --------------------------------------------------------------------

@pytest.mark.django_db
@pytest.mark.parametrize("configured", ["", "strava-other", "strava-owner"])
def test_without_an_owner_account_the_run_is_idle(strava, settings, configured):
    settings.GARAGE_STRAVA_USER = configured
    old = old_event()
    with strava.fake.serving():
        outcome = sync_all()
    assert outcome == SyncAllResult(accounts=0, pending=0, status="idle", error="", purged=0, absences=0)
    assert not strava.fake.calls and not StravaAccount.objects.exists(), "the daily run never creates the account"
    assert not StravaEvent.objects.filter(pk=old.pk).exists(), "purge_events runs first"


@pytest.mark.django_db
def test_the_daily_run_never_recreates_an_account_removed_by_hand(strava):
    from .services.strava_sources import remove_strava_data
    synced(strava, (1, ago(1)))
    remove_strava_data(strava.owner)
    with strava.fake.serving():
        calls = len(strava.fake.calls)
        assert sync_all().status == "idle"
    assert len(strava.fake.calls) == calls and not StravaAccount.objects.exists() and not strava_rows().exists()


@pytest.mark.django_db
@pytest.mark.parametrize("moment", ["before its sync", "during GET /athlete", "during the week's page"])
def test_the_daily_run_never_refills_an_account_removed_meanwhile(strava, moment):
    """Review of phase 4: «Quitar lo sincronizado» pressed while the daily run is under way (create=False)."""
    from .services.strava_sources import remove_strava_data
    synced(strava, (1, ago(1)), (2, ago(2)))
    strava.fake.add(3, start=ago(3))
    removed = []

    def remove():
        if not removed:
            removed.append(remove_strava_data(strava.owner))

    real_get, real_sync = strava.fake.get, strava_sync._sync_owner
    path = {"during GET /athlete": "/athlete", "during the week's page": "/athlete/activities"}.get(moment)

    def get(url, **kwargs):
        if path and url.endswith(path):
            remove()  # the person's POST commits while this Strava call is under way
        return real_get(url, **kwargs)

    def sync_owner(owner, **kwargs):
        if moment == "before its sync":
            remove()
        return real_sync(owner, **kwargs)

    strava.fake.get = get
    calls = len(strava.fake.calls)
    with strava.fake.serving(), patch("garage.services.strava_sync._sync_owner", side_effect=sync_owner):
        outcome = sync_all()
    assert removed and outcome == SyncAllResult(accounts=0, pending=0, status="idle", error="", purged=0, absences=0)
    assert not StravaAccount.objects.exists() and not strava_rows().exists() and not StravaGear.objects.exists()
    assert not StravaEvent.objects.exists() and not Ride.objects.exists()
    made = [item.path for item in strava.fake.calls[calls:]]
    assert made == {"before its sync": [], "during GET /athlete": ["/athlete"],
                    "during the week's page": ["/athlete", "/athlete/activities"]}[moment], "never GET /athlete to re-create it"


def test_the_deployment_checklist_checks_read_all_and_the_worker_target():
    """Review of phase 4: absence deletes only with activity:read_all, and the README copy of the Worker is redacted."""
    text = (Path(__file__).resolve().parent.parent / "docs" / "garage-handoff.md").read_text()
    start = text.index("## Despliegue (garage-023)")
    block = text[start:text.index("\n## ", start + 1)]
    assert "activity:read_all" in block and "privada" in block, "check the token's scope with a private test ride"
    assert "TARGET" in block and "/healthz/" in block, "restore the live keep-alive URL before Deploy"
    assert "/sync-all/" in block and "https" in block


@pytest.mark.django_db
@pytest.mark.parametrize("trigger", ["button", "daily"])
def test_the_daily_run_does_exactly_what_the_button_does(strava, trigger):
    connected(strava)
    strava.fake.add(1, start=ago(2), gear="b1")
    strava.fake.add(2, start=ago(3), sport="Run")
    strava.fake.add(3, start=ago(30))  # outside the window: never asked
    strava.fake.add(4, start=ago(40))
    hint(4, "create")
    calls = len(strava.fake.calls)
    with strava.fake.serving(), patch("garage.services.strava_sync._sync_owner", wraps=strava_sync._sync_owner) as spy:
        if trigger == "button":
            result = sync_now(strava.owner)
            pending, error, absences = result.pending + (not result.complete), result.error, result.absences
        else:
            outcome = sync_all()
            pending, error, absences = outcome.pending, outcome.error, outcome.absences
            assert (outcome.status, outcome.accounts, outcome.purged) == ("ok", 1, 0)
    spy.assert_called_once()
    assert spy.call_args.args[0].pk == strava.owner.pk
    assert [item.path for item in strava.fake.calls[calls:]] == ["/athlete", "/athlete/activities", "/activities/4"]
    assert (pending, error, absences) == (0, "", 0)
    assert set(strava_rows().values_list("external_id", flat=True)) == {1, 4}
    account = StravaAccount.objects.get()
    assert (account.last_sync_status, account.last_error_code, account.revoked_at) == ("ok", "", None)
    assert not StravaEvent.objects.filter(processed_at__isnull=True).exists()


@pytest.mark.django_db
def test_an_incomplete_week_asks_the_worker_to_call_again(strava, small_pages):
    synced(strava, *((key, ago(1, minutes=10 * key)) for key in range(1, 5)))
    for key in range(5, 7):
        strava.fake.add(key, start=ago(1, minutes=10 * key))
    strava.fake.delete(1)  # absent, but the week is not read whole: no absence hint
    with strava.fake.serving():
        outcome = sync_all()
    assert (outcome.status, outcome.pending, outcome.absences, outcome.error) == ("ok", 1, 0, "")
    assert not absence_hints().exists() and strava_rows().filter(external_id=1).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["/athlete", "/athlete/activities"])
def test_a_stop_code_fails_the_run_and_leaves_the_hints_as_they_are(strava, path):
    synced(strava, (1, ago(1)))
    strava.fake.delete(1)
    waiting = hint(5, "create")
    strava.fake.script(path, FakeResponse(429, "{}", {"X-RateLimit-Usage": "600,30000"}))
    calls = len(strava.fake.calls)
    with strava.fake.serving():
        outcome = sync_all()
    assert outcome == SyncAllResult(accounts=1, pending=1, status="failed", error="rate_limited", purged=0, absences=0)
    made = [item.path for item in strava.fake.calls[calls:]]
    assert made[-1] == path and made.count(path) == 1, "no retry and no other call after the 429"
    waiting.refresh_from_db()
    assert (waiting.processed_at, waiting.attempts) == (None, 0) and not absence_hints().exists()
    account = StravaAccount.objects.get()
    assert (account.last_sync_status, account.last_error_code, account.revoked_at) == ("failed", "rate_limited", None)


@pytest.mark.django_db
def test_the_run_logs_one_info_line_with_codes_only(strava, caplog):
    synced(strava, (1, ago(1)))
    caplog.set_level(logging.INFO, logger="garage")
    with strava.fake.serving():
        sync_all()
    lines = [record for record in caplog.records if record.getMessage().startswith("Garage Strava daily sync")]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO and lines[0].name.split(".")[0] == "garage"
    assert lines[0].getMessage() == ("Garage Strava daily sync: status=ok error=none accounts=1 purged=0 absences=0 "
                                     "pending=0 old_events=0.")
    assert not any(text in caplog.text for text in ("Ana", "Prueba", "strava-owner", "synthetic-access"))


# Absence as a deletion hint --------------------------------------------------

@pytest.mark.django_db
def test_an_absent_known_activity_becomes_a_hint_and_a_404_deletes_it(strava):
    account = synced(strava, (1, ago(1)), (2, ago(2)))
    ride_id = strava_rows().get(external_id=1).ride_id
    strava.fake.delete(1)
    calls = len(strava.fake.calls)
    with strava.fake.serving():
        outcome = sync_all()
    assert (outcome.status, outcome.absences, outcome.pending) == ("ok", 1, 0)
    assert "/activities/1" in [item.path for item in strava.fake.calls[calls:]]
    event = absence_hints().get()
    assert (event.subscription_id, event.athlete_id, event.object_type, event.aspect_type, event.object_id) == \
        (0, account.athlete_id, "activity", "delete", 1)
    assert event.updates == {"origin": "absence"} and event.processed_at is not None and event.error_code == ""
    assert abs((event.event_time - (timezone.now() - timedelta(days=7))).total_seconds()) < 60
    assert event.event_time.microsecond == 0, "the window's own epoch second"
    assert not strava_rows().filter(external_id=1).exists() and not Ride.objects.filter(pk=ride_id).exists()
    assert strava_rows().filter(external_id=2).exists()
    with strava.fake.serving():
        assert sync_all().absences == 0, "nothing absent any more"


@pytest.mark.django_db
def test_a_404_keeps_rides_with_a_fit_or_a_measurement_correction(strava):
    g = SimpleNamespace(owner=strava.owner)
    fit_ride, _ = fit(g, ago(1))
    connected(strava)
    strava.fake.add(1, start=ago(1))  # joins the FIT ride (same start and distance)
    strava.fake.add(2, start=ago(2))
    strava.fake.add(3, start=ago(3))
    with strava.fake.serving():
        assert sync_now(strava.owner).error == ""
    assert strava_rows().get(external_id=1).ride_id == fit_ride.pk
    corrected = strava_rows().get(external_id=2).ride_id
    correct_ride(strava.owner, corrected, distance_m=Decimal("10"))
    only_strava = strava_rows().get(external_id=3).ride_id
    for key in (1, 2, 3):
        strava.fake.delete(key)
    with strava.fake.serving():
        assert sync_all().absences == 3
    assert not strava_rows().exists()
    assert set(Ride.objects.values_list("pk", flat=True)) == {fit_ride.pk, corrected}
    assert not Ride.objects.filter(pk=only_strava).exists()
    assert Ride.objects.get(pk=corrected).distance_m == Decimal("10.000")


@pytest.mark.django_db
def test_still_on_strava_it_is_kept_and_updated_and_no_longer_cycling_it_goes(strava):
    synced(strava, (1, ago(1)), (2, ago(2)))
    strava.fake.add(1, start=ago(1), name="Renombrada")
    strava.fake.add(2, start=ago(2), sport="Run")
    strava.fake.script("/athlete/activities", FakeResponse(200, "[]"))  # Strava's list did not name them this time
    with strava.fake.serving():
        outcome = sync_all()
    assert (outcome.status, outcome.absences, outcome.pending) == ("ok", 2, 0)
    kept = strava_rows().get(external_id=1)
    assert kept.name == "Renombrada" and kept.ride.name == "Renombrada"
    assert not strava_rows().filter(external_id=2).exists()
    assert all(event.processed_at is not None and event.error_code == "" for event in absence_hints())


@pytest.mark.django_db
def test_withdrawn_old_and_listed_sources_get_no_hint(strava):
    account = synced(strava, (1, ago(1)), (2, ago(2)))
    withdraw_source(strava.owner, strava_rows().get(external_id=1).pk)
    store(SimpleNamespace(owner=strava.owner, account=account), 80, start=ago(10))  # before the window
    strava.fake.delete(1)
    with strava.fake.serving():
        assert sync_all().absences == 0
    assert not absence_hints().exists() and strava_rows().filter(external_id__in=(1, 2, 80)).count() == 3


@pytest.mark.django_db
def test_without_read_all_absence_proves_nothing(strava):
    account = synced(strava, (1, ago(1)))
    StravaAccount.objects.filter(pk=account.pk).update(scopes="read")
    strava.fake.delete(1)
    with strava.fake.serving():
        assert sync_all().absences == 0
    assert not absence_hints().exists() and strava_rows().filter(external_id=1).exists()


@pytest.mark.django_db
def test_a_week_with_an_unusable_activity_gives_no_hints(strava):
    synced(strava, (1, ago(1)))
    broken = activity_text(9, start=ago(2)).replace('"start_date": "', '"start_date": "x')
    strava.fake.script("/athlete/activities", FakeResponse(200, f"[{broken}]"))
    with strava.fake.serving():
        outcome = sync_all()
    assert (outcome.status, outcome.absences) == ("partial", 0)
    assert not absence_hints().exists() and strava_rows().filter(external_id=1).exists()


@pytest.mark.django_db
def test_a_failed_confirmation_leaves_the_hint_pending(strava):
    synced(strava, (1, ago(1)))
    strava.fake.script("/athlete/activities", FakeResponse(200, "[]"))
    strava.fake.script("/activities/1", FakeResponse(500))
    with strava.fake.serving():
        outcome = sync_all()
    assert (outcome.status, outcome.error, outcome.absences, outcome.pending) == ("failed", "network", 1, 1)
    event = absence_hints().get()
    assert event.processed_at is None and event.error_code == "network" and strava_rows().filter(external_id=1).exists()
    with strava.fake.serving():  # the next run confirms it (still on Strava) and creates no second hint
        outcome = sync_all()
    assert (outcome.status, outcome.absences, outcome.pending) == ("ok", 0, 0)
    event.refresh_from_db()
    assert event.processed_at is not None and absence_hints().count() == 1 and strava_rows().filter(external_id=1).exists()


@pytest.mark.django_db
def test_hints_are_capped_deduplicated_and_count_as_pending(strava):
    synced(strava, *((key, ago(1, minutes=key)) for key in range(1, 4)))
    for key in range(1, 4):
        strava.fake.delete(key)
    with strava.fake.serving(), patch("garage.services.strava_sync.ABSENCE_HINTS", 2), \
         patch("garage.services.strava_sync.SYNC_EVENTS", 0):
        first, second, third = sync_all(), sync_all(), sync_all()
    assert [(run.absences, run.pending) for run in (first, second, third)] == [(2, 2), (1, 3), (0, 3)]
    assert absence_hints().count() == 3 and strava_rows().count() == 3
    with strava.fake.serving():
        outcome = sync_all()
    assert (outcome.absences, outcome.pending) == (0, 0) and not strava_rows().exists()


@pytest.mark.django_db
def test_absence_respects_the_pending_cap(strava):
    synced(strava, *((key, ago(1, minutes=key)) for key in range(1, 4)))
    StravaEvent.objects.bulk_create([StravaEvent(subscription_id=120, athlete_id=ATHLETE, object_type="activity",
                                                 aspect_type="update", object_id=1000 + key, event_time=at())
                                     for key in range(PENDING_CAP - 1)])
    for key in range(1, 4):
        strava.fake.delete(key)
    with strava.fake.serving(), patch("garage.services.strava_sync.SYNC_EVENTS", 0):
        assert sync_all().absences == 1
        assert sync_all().absences == 0
    assert StravaEvent.objects.filter(processed_at__isnull=True).count() == PENDING_CAP


# Revocation and the 30-day purge ---------------------------------------------

def revoked(days):
    return timezone.now() - timedelta(days=days)


@pytest.mark.django_db
def test_a_persistent_401_marks_the_account_revoked_once(strava):
    synced(strava, (1, ago(1)))
    strava.fake.script("/athlete", FakeResponse(401), FakeResponse(401))
    with strava.fake.serving():
        assert sync_now(strava.owner).error == "unauthorized"
    first = StravaAccount.objects.get().revoked_at
    assert first is not None
    assert not accept_event({"object_type": "activity", "aspect_type": "create", "object_id": 7, "owner_id": ATHLETE,
                             "subscription_id": 120, "event_time": 1767261600}), "the webhook ignores a revoked athlete"
    strava.fake.script("/athlete", FakeResponse(401), FakeResponse(401))
    with strava.fake.serving():
        assert sync_all().error == "unauthorized"
    account = StravaAccount.objects.get()
    assert account.revoked_at == first and (account.last_sync_status, account.last_error_code) == ("failed", "unauthorized")
    hint(4, "create")
    strava.fake.add(4, start=ago(40))  # outside the week: only its hint can bring it
    with strava.fake.serving():
        assert sync_now(strava.owner).error == ""
    assert StravaAccount.objects.get().revoked_at is None
    assert strava_rows().filter(external_id=4).exists(), "the hints resume in the same run"


RENEWAL = "garage.services.strava_client.refresh_access_token"


def rejected_renewal():
    import requests
    return patch(RENEWAL, side_effect=requests.HTTPError(response=SimpleNamespace(status_code=400)))


@pytest.mark.django_db
def test_a_renewal_rejected_is_unauthorized_too_and_only_a_successful_end_clears_the_mark(strava):
    """Review of phase 4: a network failure, a 429 or an unusable answer proves nothing about the token."""
    import requests
    synced(strava, (1, ago(1)))
    with rejected_renewal(), patch("garage.services.strava_client.requests.get") as get:
        assert sync_all().error == "unauthorized"
    get.assert_not_called()
    first = StravaAccount.objects.get().revoked_at
    assert first is not None
    failures = [("network", lambda: strava.fake.script("/athlete", FakeResponse(500))),
                ("rate_limited", lambda: strava.fake.script("/athlete", FakeResponse(429, "{}"))),
                ("invalid_response", lambda: strava.fake.script("/athlete", FakeResponse(200, "[]")))]
    for code, arrange in failures:
        arrange()
        with strava.fake.serving():
            assert sync_all().error == code
        account = StravaAccount.objects.get()
        assert (account.revoked_at, account.last_error_code) == (first, code), code
    for failure, code in ((requests.ConnectionError(), "network"), (KeyError("access_token"), "invalid_response")):
        with patch(RENEWAL, side_effect=failure), patch("garage.services.strava_client.requests.get") as get:
            assert sync_all().error == code
        assert StravaAccount.objects.get().revoked_at == first, code
    with strava.fake.serving():
        assert sync_all().error == ""
    assert StravaAccount.objects.get().revoked_at is None, "a successful end clears the mark"


@pytest.mark.django_db
def test_a_network_end_never_restarts_the_30_day_clock(strava):
    """Review probe: revoked 29 days ago, an unreachable token endpoint one morning, then the 401 again."""
    import requests
    account = synced(strava, (1, ago(1)))
    since = revoked(29)
    StravaAccount.objects.filter(pk=account.pk).update(revoked_at=since)
    with patch(RENEWAL, side_effect=requests.ConnectionError()), patch("garage.services.strava_client.requests.get") as get:
        assert sync_all().error == "network"
    get.assert_not_called()
    assert StravaAccount.objects.get().revoked_at == since
    strava.fake.script("/athlete", FakeResponse(401), FakeResponse(401))
    with strava.fake.serving():
        assert sync_all().error == "unauthorized"
    assert StravaAccount.objects.get().revoked_at == since


@pytest.mark.django_db
@pytest.mark.parametrize("revoked_days", [None, 31])
@pytest.mark.parametrize("case", ["403 on one hint", "401 on the activities"])
def test_a_401_or_403_after_strava_accepted_the_token_never_marks_the_account_revoked(strava, case, revoked_days):
    """Review of phase 4: GET /athlete answered, so the token works; one hint's 403 or a missing scope is no revocation."""
    account = synced(strava, (1, ago(1)))
    if revoked_days:
        StravaAccount.objects.filter(pk=account.pk).update(revoked_at=revoked(revoked_days))
    if case == "403 on one hint":
        hint(5, "create")
        strava.fake.script("/activities/5", FakeResponse(403))
    else:
        strava.fake.script("/athlete/activities", FakeResponse(401), FakeResponse(401))
    with strava.fake.serving():
        outcome = sync_all()
    assert (outcome.status, outcome.error, outcome.purged, outcome.accounts) == ("failed", "unauthorized", 0, 1)
    account = StravaAccount.objects.get()
    assert (account.revoked_at, account.last_sync_status, account.last_error_code) == (None, "failed", "unauthorized")
    assert strava_rows().filter(external_id=1).exists(), "never purged: Strava accepted the token in this run"
    assert accept_event({"object_type": "activity", "aspect_type": "create", "object_id": 77, "owner_id": ATHLETE,
                         "subscription_id": 120, "event_time": 1767261600}), "the webhook keeps listening"


def purge_fixture(strava):
    """A Strava-only ride, one with a measurement correction, one with a FIT, gear, hints and a revoked account."""
    g = SimpleNamespace(owner=strava.owner)
    with_fit, _ = fit(g, ago(3))
    account = synced(strava, (1, ago(1)), (2, ago(2)), (3, ago(3)))
    correct_ride(strava.owner, strava_rows().get(external_id=2).ride_id, moving_time_s=Decimal("100"))
    hint(5, "create")
    StravaEvent.objects.create(subscription_id=0, athlete_id=ATHLETE, object_type="activity", aspect_type="delete", object_id=1,
                               event_time=ago(7), updates={"origin": "absence"})
    return account, {"only": strava_rows().get(external_id=1).ride_id, "corrected": strava_rows().get(external_id=2).ride_id,
                     "fit": with_fit.pk}


def utc(text):
    from datetime import datetime
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# (revoked_at, the daily run): the purge day is the 30th Madrid day after the revocation's own, the day the page shows.
ON_THE_PURGE_DATE = {
    # 09:05:20 CET, purged at 09:05 CEST: 30 days minus 1 h, the date shown (19 abr), not a day later.
    "spring": ("2026-03-20T08:05:20Z", "2026-04-19T07:05:00Z"),
    # 09:05:20 CEST, purged at 09:05 CET of the 30th day (9 nov).
    "autumn": ("2026-10-10T07:05:20Z", "2026-11-09T08:05:00Z"),
    # A press at 00:30 CEST on 11 oct: purged on 10 nov, never on 9 nov.
    "after midnight": ("2026-10-10T22:30:00Z", "2026-11-10T08:05:00Z"),
    # Days later (the Worker was down): still only when Strava rejects the token.
    "later": ("2026-03-20T08:05:20Z", "2026-05-02T07:05:00Z"),
}
THE_DAY_BEFORE = {
    "spring": ("2026-03-20T08:05:20Z", "2026-04-18T07:05:00Z"),
    "autumn": ("2026-10-10T07:05:20Z", "2026-11-08T08:05:00Z"),
    # 23:59 CET on 9 nov is 30 days and 29 minutes after it: still the day before the date shown.
    "after midnight": ("2026-10-10T22:30:00Z", "2026-11-09T22:59:00Z"),
}


@pytest.mark.django_db
@pytest.mark.parametrize("case", sorted(ON_THE_PURGE_DATE) + ["31 days ago"])
def test_on_its_purge_date_the_daily_run_purges_when_strava_still_rejects_the_token(strava, case):
    from .services.strava_sync import DAILY_SYNC_ZONE, purge_date
    account, rides = purge_fixture(strava)
    since, now = (revoked(31), None) if case == "31 days ago" else map(utc, ON_THE_PURGE_DATE[case])
    StravaAccount.objects.filter(pk=account.pk).update(revoked_at=since)
    if now is not None and case != "later":
        assert purge_date(since) == timezone.localtime(now, DAILY_SYNC_ZONE).date(), "the run is on the date shown"
    strava.fake.script("/athlete", FakeResponse(401), FakeResponse(401))
    calls, tokens = len(strava.fake.calls), strava.fake.tokens
    with strava.fake.serving():
        outcome = sync_all(now=now)
    assert outcome == SyncAllResult(accounts=1, pending=0, status="ok", error="", purged=1, absences=0)
    assert [item.path for item in strava.fake.calls[calls:]] == ["/athlete", "/athlete"], "checked with Strava first"
    assert strava.fake.tokens - tokens == 2, "a renewal, a 401, another renewal, the 401 again"
    assert not StravaAccount.objects.exists() and not StravaEvent.objects.exists() and not StravaGear.objects.exists()
    assert not strava_rows().exists()
    assert set(Ride.objects.values_list("pk", flat=True)) == {rides["corrected"], rides["fit"]}


@pytest.mark.django_db
@pytest.mark.parametrize("case", sorted(THE_DAY_BEFORE))
def test_the_day_before_its_purge_date_it_only_tries_again(strava, case):
    account, rides = purge_fixture(strava)
    since, now = map(utc, THE_DAY_BEFORE[case])
    StravaAccount.objects.filter(pk=account.pk).update(revoked_at=since)
    strava.fake.script("/athlete", FakeResponse(401), FakeResponse(401))
    with strava.fake.serving():
        outcome = sync_all(now=now)
    assert (outcome.purged, outcome.status, outcome.error, outcome.accounts) == (0, "failed", "unauthorized", 1)
    assert StravaAccount.objects.get().revoked_at == since and strava_rows().count() == 3
    assert set(rides.values()) <= set(Ride.objects.values_list("pk", flat=True))


@pytest.mark.django_db
def test_past_its_purge_date_a_token_that_works_again_is_never_purged(strava):
    """Review of phase 4: STRAVA_REFRESH_TOKEN renewed after the last failing run, or the Worker back after day 30."""
    account, rides = purge_fixture(strava)
    StravaAccount.objects.filter(pk=account.pk).update(revoked_at=revoked(31))
    calls = len(strava.fake.calls)
    with strava.fake.serving():
        outcome = sync_all()
    assert (outcome.status, outcome.error, outcome.purged, outcome.accounts) == ("ok", "", 0, 1)
    assert strava.fake.paths()[calls] == "/athlete"
    account = StravaAccount.objects.get()
    assert (account.revoked_at, account.last_sync_status) == (None, "ok")
    assert strava_rows().count() == 3 and StravaGear.objects.exists()
    assert set(rides.values()) <= set(Ride.objects.values_list("pk", flat=True))


@pytest.mark.django_db
@pytest.mark.parametrize("failure", ["renewal unreachable", "429", "500"])
def test_past_its_purge_date_a_network_failure_or_a_429_skips_the_purge_that_day(strava, failure):
    import requests
    account, rides = purge_fixture(strava)
    since = revoked(31)
    StravaAccount.objects.filter(pk=account.pk).update(revoked_at=since)
    if failure == "renewal unreachable":
        with patch(RENEWAL, side_effect=requests.ConnectionError()), patch("garage.services.strava_client.requests.get"):
            outcome = sync_all()
    else:
        strava.fake.script("/athlete", FakeResponse(int(failure), "{}"))
        with strava.fake.serving():
            outcome = sync_all()
    code = "rate_limited" if failure == "429" else "network"
    assert (outcome.status, outcome.error, outcome.purged, outcome.accounts) == ("failed", code, 0, 1)
    assert StravaAccount.objects.get().revoked_at == since and strava_rows().count() == 3 and StravaGear.objects.exists()


@pytest.mark.django_db
def test_the_button_never_purges(strava):
    account, _ = purge_fixture(strava)
    since = revoked(45)
    StravaAccount.objects.filter(pk=account.pk).update(revoked_at=since)
    strava.fake.script("/athlete", FakeResponse(401), FakeResponse(401))
    with strava.fake.serving():
        assert sync_now(strava.owner).error == "unauthorized"
    assert StravaAccount.objects.get().revoked_at == since and strava_rows().count() == 3 and StravaGear.objects.exists()
    with strava.fake.serving():  # Strava accepts the token again: nothing purged, the mark goes
        assert sync_now(strava.owner).error == ""
    assert StravaAccount.objects.get().revoked_at is None and strava_rows().count() == 3


# Commands --------------------------------------------------------------------

def test_garage_sync_token_prints_a_fresh_token_and_writes_nothing(tmp_path, monkeypatch):
    """No database mark: any query would fail. Nothing appears in the working directory or the repository."""
    repository = Path(__file__).resolve().parent.parent
    before = sorted(path.name for path in repository.iterdir())
    monkeypatch.chdir(tmp_path)
    outputs = []
    for _ in range(2):
        out = StringIO()
        call_command("garage_sync_token", stdout=out)
        outputs.append(out.getvalue())
    tokens = [output.strip() for output in outputs]
    assert all(output.count("\n") == 1 for output in outputs) and tokens[0] != tokens[1]
    assert all(len(token) >= 32 and re.fullmatch(r"[A-Za-z0-9_-]+", token) for token in tokens)
    assert not list(tmp_path.iterdir()) and sorted(path.name for path in repository.iterdir()) == before


@pytest.mark.django_db
def test_garage_strava_sync_prints_the_json(strava, settings):
    out = StringIO()
    settings.GARAGE_STRAVA_USER = ""
    call_command("garage_strava_sync", stdout=out)
    assert json.loads(out.getvalue()) == {"pending": 0, "status": "idle", "error": "", "accounts": 0, "purged": 0, "absences": 0}
    settings.GARAGE_STRAVA_USER = "strava-owner"
    synced(strava, (1, ago(1)))
    strava.fake.delete(1)
    out = StringIO()
    with strava.fake.serving():
        call_command("garage_strava_sync", stdout=out)
    assert json.loads(out.getvalue()) == {"pending": 0, "status": "ok", "error": "", "accounts": 1, "purged": 0, "absences": 1}
    assert not strava_rows().exists()
