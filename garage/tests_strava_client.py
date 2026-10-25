"""Strava client and token-mode account (garage-030), with a simulated Strava.

FakeStrava answers mocked `requests.get` calls with JSON *text*, so the client's
json.loads(..., parse_float=Decimal) is what turns numbers into values. No real
HTTP is ever made: the test bootstrap blocks sockets as well.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from .models import StravaAccount, StravaGear
from .services.strava_client import API_BASE, TIMEOUT, StravaClient, StravaError
from .services.strava_sync import ENV_SCOPES, ensure_account, strava_status

ATHLETE = 4242


def at(day=1, hour=10, minute=0, second=0):
    return datetime(2026, 3, day, hour, minute, second, tzinfo=datetime_timezone.utc)


class FakeResponse:
    def __init__(self, status=200, text="{}", headers=None):
        self.status_code, self.text, self.headers = status, text, headers or {}


def activity_text(activity_id, *, start, distance="30000.0", sport="Ride", name="Vuelta", moving="3600", elapsed="4000",
                  gear=None, athlete=ATHLETE, extra=""):
    """Literal JSON text: numbers stay exactly as Strava would write them."""
    return ('{"id": %d, "athlete": {"id": %d}, "name": %s, "sport_type": %s, "type": %s, "start_date": "%s", '
            '"distance": %s, "moving_time": %s, "elapsed_time": %s, "gear_id": %s, "total_elevation_gain": 12.3%s}'
            % (activity_id, athlete, json.dumps(name), json.dumps(sport), json.dumps(sport), start.strftime("%Y-%m-%dT%H:%M:%SZ"),
               distance, moving, elapsed, json.dumps(gear), extra))


class FakeStrava:
    """In-memory Strava: activities, one athlete, scripted statuses and a call log."""

    def __init__(self, athlete=ATHLETE, bikes=None):
        self.athlete_id = athlete
        self.bikes = bikes if bikes is not None else [{"id": "b1", "name": "Strava Gravel", "retired": False}]
        self.texts = {}
        self.starts = {}
        self.overrides = {}  # path -> list of FakeResponse used once each, then normal behaviour
        self.calls = []
        self.tokens = 0

    def add(self, activity_id, *, start, **values):
        self.texts[activity_id] = activity_text(activity_id, start=start, **values)
        self.starts[activity_id] = start
        return activity_id

    def delete(self, activity_id):
        self.texts.pop(activity_id, None)
        self.starts.pop(activity_id, None)

    def script(self, path, *responses):
        self.overrides.setdefault(path, []).extend(responses)

    def token(self):
        self.tokens += 1
        return f"synthetic-access-{self.tokens}"

    def get(self, url, headers=None, params=None, timeout=None):
        assert url.startswith(API_BASE + "/")
        path = url[len(API_BASE):]
        self.calls.append(SimpleNamespace(path=path, params=dict(params or {}), timeout=timeout, headers=dict(headers or {})))
        if self.overrides.get(path):
            return self.overrides[path].pop(0)
        if path == "/athlete":
            return FakeResponse(200, json.dumps({"id": self.athlete_id, "firstname": "Ana", "lastname": "Prueba", "bikes": self.bikes}))
        if path == "/athlete/activities":
            after, page, per_page = params["after"], params["page"], params["per_page"]
            ids = sorted((key for key, start in self.starts.items() if start.timestamp() > after), key=lambda key: (self.starts[key], key))
            chunk = ids[(page - 1) * per_page: page * per_page]
            return FakeResponse(200, "[" + ", ".join(self.texts[key] for key in chunk) + "]")
        if path.startswith("/activities/"):
            key = int(path.rsplit("/", 1)[1])
            if key in self.texts:
                return FakeResponse(200, self.texts[key])
            return FakeResponse(404, '{"message": "Record Not Found"}')
        return FakeResponse(404, "{}")

    @contextmanager
    def serving(self):
        with patch("garage.services.strava_client.requests.get", side_effect=self.get) as get, \
             patch("garage.services.strava_client.refresh_access_token", side_effect=self.token):
            yield get

    def paths(self):
        return [call.path for call in self.calls]


@pytest.fixture
def strava(db, django_user_model, settings):
    from .services import strava_sync
    owner = django_user_model.objects.create_user(username="strava-owner")
    other = django_user_model.objects.create_user(username="strava-other")
    settings.GARAGE_STRAVA_USER = "strava-owner"
    strava_sync._workers.clear()  # a mocked thread never releases its athlete
    yield SimpleNamespace(owner=owner, other=other, fake=FakeStrava())
    strava_sync._workers.clear()


def connected(strava):
    with strava.fake.serving():
        account, _ = ensure_account(strava.owner, StravaClient())
    return account


@pytest.mark.django_db
def test_every_call_has_a_timeout_and_decimal_numbers(strava):
    strava.fake.add(7, start=at(), distance="123456789012345.678", moving="3600")
    with strava.fake.serving():
        client = StravaClient()
        data = client.activity(7)
        rows = client.activities(after=0, page=1)
        client.athlete()
    assert all(call.timeout == TIMEOUT == (5, 20) for call in strava.fake.calls)
    # A float intermediate could not keep 18 significant digits.
    assert data["distance"] == Decimal("123456789012345.678") and isinstance(data["distance"], Decimal)
    assert isinstance(data["total_elevation_gain"], Decimal) and data["moving_time"] == 3600
    assert rows[0]["id"] == 7 and strava.fake.tokens == 1, "one token renewal per client"
    assert strava.fake.calls[1].params == {"after": 0, "page": 1, "per_page": 50}
    assert strava.fake.calls[0].headers == {"Authorization": "Bearer synthetic-access-1"}


@pytest.mark.django_db
def test_401_renews_once_then_reports_unauthorized(strava):
    strava.fake.add(7, start=at())
    strava.fake.script("/activities/7", FakeResponse(401))
    with strava.fake.serving():
        assert StravaClient().activity(7)["id"] == 7
    assert strava.fake.tokens == 2
    strava.fake.script("/activities/7", FakeResponse(401), FakeResponse(401))
    with strava.fake.serving(), pytest.raises(StravaError) as error:
        StravaClient().activity(7)
    assert error.value.code == "unauthorized" and strava.fake.tokens == 4


@pytest.mark.django_db
@pytest.mark.parametrize("response,code", [
    (FakeResponse(429, "{}", {"X-RateLimit-Usage": "101,950"}), "rate_limited"),
    (FakeResponse(403), "unauthorized"), (FakeResponse(404), "not_found"), (FakeResponse(502), "network"),
    (FakeResponse(200, "not json"), "invalid_response"), (FakeResponse(200, "[]"), "invalid_response"),
])
def test_http_failures_become_codes(strava, response, code):
    strava.fake.script("/activities/9", response)
    with strava.fake.serving(), pytest.raises(StravaError) as error:
        StravaClient().activity(9)
    assert error.value.code == code
    if code == "rate_limited":
        assert error.value.usage == "101,950"


@pytest.mark.django_db
@pytest.mark.parametrize("failure,code", [(requests.Timeout(), "network"), (requests.ConnectionError(), "network")])
def test_network_errors_and_timeouts(strava, failure, code):
    with patch("garage.services.strava_client.requests.get", side_effect=failure), \
         patch("garage.services.strava_client.refresh_access_token", return_value="synthetic"), pytest.raises(StravaError) as error:
        StravaClient().athlete()
    assert error.value.code == code


@pytest.mark.django_db
@pytest.mark.parametrize("failure,code", [
    (requests.HTTPError(response=FakeResponse(400)), "unauthorized"), (requests.HTTPError(response=FakeResponse(503)), "network"),
    (requests.ConnectionError(), "network"), (KeyError("access_token"), "invalid_response"),
])
def test_token_renewal_failures(strava, failure, code):
    with patch("garage.services.strava_client.refresh_access_token", side_effect=failure), \
         patch("garage.services.strava_client.requests.get") as get, pytest.raises(StravaError) as error:
        StravaClient().athlete()
    assert error.value.code == code
    get.assert_not_called()


@pytest.mark.django_db
def test_env_account_from_get_athlete_without_tokens(strava):
    status = strava_status(strava.owner)
    assert status.configured and status.is_owner and status.account is None
    account = connected(strava)
    assert (account.owner, account.athlete_id, account.athlete_name, account.mode) == (strava.owner, ATHLETE, "Ana Prueba", "env")
    assert account.access_token_enc == account.refresh_token_enc == "" and account.scopes == ENV_SCOPES and account.can_confirm_deletes
    assert StravaGear.objects.get(owner=strava.owner).name == "Strava Gravel"
    calls = len(strava.fake.calls)
    assert connected(strava) == account and len(strava.fake.calls) == calls, "an existing account needs no call"


@pytest.mark.django_db
def test_account_requires_the_configured_user(strava, settings):
    for user, configured in ((strava.other, "strava-owner"), (strava.owner, ""), (strava.owner, "missing-user")):
        settings.GARAGE_STRAVA_USER = configured
        with strava.fake.serving(), pytest.raises(StravaError) as error:
            ensure_account(user, StravaClient())
        assert error.value.code == "not_configured"
    assert not strava.fake.calls and not StravaAccount.objects.exists()
    settings.GARAGE_STRAVA_USER = "strava-owner"
    assert not strava_status(strava.other).is_owner and strava_status(strava.other).configured


@pytest.mark.django_db
def test_an_athlete_belongs_to_one_garage_user(strava, settings):
    connected(strava)
    settings.GARAGE_STRAVA_USER = "strava-other"
    with strava.fake.serving(), pytest.raises(StravaError) as error:
        ensure_account(strava.other, StravaClient())
    assert error.value.code == "athlete_taken" and StravaAccount.objects.count() == 1


@pytest.mark.django_db
def test_env_account_constraints(strava):
    from django.db import IntegrityError, transaction
    account = connected(strava)
    for changes in ({"access_token_enc": "secret"}, {"mode": "other"}, {"athlete_id": 0}, {"last_error_code": "boom"}):
        with pytest.raises(IntegrityError), transaction.atomic():
            StravaAccount.objects.filter(pk=account.pk).update(**changes)
    assert str(account) == f"Strava athlete {ATHLETE}"
    account.access_token_enc = "secret"
    with pytest.raises(Exception):
        account.full_clean()


def test_activity_text_is_valid_json():
    assert json.loads(activity_text(1, start=at()), parse_float=Decimal)["distance"] == Decimal("30000.0")
    assert at(2) - at(1) == timedelta(days=1)
