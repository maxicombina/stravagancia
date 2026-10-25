"""Más → Strava, ride source screens and export (garage-030). GET never writes nor calls Strava."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .importers.fit import FIT_EPOCH
from .models import ActivitySource, Bike, ImportRun, Ride, StravaAccount, StravaGear
from .services.export import TABLES, csv_zip, export_snapshot
from .services.ownership import create_inventory
from .tests_fit_import import activity
from .tests_strava_client import FakeResponse, at, connected, strava  # noqa: F401 (fixture)
from .tests_strava_sources import fit, store


def writes(queries):
    return [q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}]


def texts(response):
    return [str(message) for message in get_messages(response.wsgi_request)]


@pytest.fixture
def web(strava, client):
    client.force_login(strava.owner)
    strava.client = client
    strava.bike = create_inventory(strava.owner, Bike, name="Gravel de Garage")
    return strava


def ns(web):
    """The sources helpers expect `owner` and `account`."""
    web.account = StravaAccount.objects.get(owner=web.owner)
    return web


def html(response):
    return response.content.decode()


@pytest.mark.django_db
def test_more_menu_links_strava(web):
    assert reverse("garage:strava") in html(web.client.get(reverse("garage:more")))


@pytest.mark.django_db
@pytest.mark.parametrize("configured,expected", [("", "Sin configurar: GARAGE_STRAVA_USER"),
                                                 ("strava-other", "configurado para otro usuario"),
                                                 ("strava-owner", "Todavía sin sincronizar")])
def test_page_states_without_writes_or_http(web, settings, configured, expected):
    settings.GARAGE_STRAVA_USER = configured
    with patch("garage.services.strava_client.requests.get") as get, \
         patch("garage.services.strava_client.refresh_access_token") as token, CaptureQueriesContext(connection) as queries:
        response = web.client.get(reverse("garage:strava"))
    assert response.status_code == 200 and expected in html(response) and "Powered by Strava" in html(response)
    assert not writes(queries)
    get.assert_not_called()
    token.assert_not_called()
    assert ("Sincronizar ahora" in html(response)) is (configured == "strava-owner")
    assert response["Cache-Control"].startswith("max-age=0")


@pytest.mark.django_db
def test_connected_page_lists_state_gear_and_removal(web):
    connected(web)
    with CaptureQueriesContext(connection) as queries:
        page = html(web.client.get(reverse("garage:strava")))
    assert not writes(queries) and len(queries) <= 20, len(queries)
    for text in ("Conectado con el token de Stravagancia (atleta Ana Prueba)", "Strava Gravel", "Sin vincular",
                 "Importar histórico", "Quitar lo sincronizado", 'type="date"', "todavía ninguna"):
        assert text in page, text


@pytest.mark.django_db
def test_sync_button(web):
    with web.fake.serving():
        response = web.client.post(reverse("garage:strava-sync"))
    assert response.status_code == 302 and response["Location"] == reverse("garage:strava")
    assert any(text.startswith("Sincronizado con Strava: 0 salidas nuevas") for text in texts(response))
    assert StravaAccount.objects.get().last_sync_status == "ok"
    web.fake.script("/athlete", FakeResponse(429))
    with web.fake.serving():
        response = web.client.post(reverse("garage:strava-sync"))
    assert any("límite de peticiones" in text for text in texts(response))
    assert web.client.get(reverse("garage:strava-sync")).status_code == 405


@pytest.mark.django_db
def test_other_users_cannot_sync_or_import(web, client):
    client.force_login(web.other)
    with web.fake.serving():
        for name, data in (("garage:strava-sync", {}), ("garage:strava-import", {"after": "2026-01-01"})):
            response = client.post(reverse(name), data)
            assert response.status_code == 302 and any("GARAGE_STRAVA_USER" in text for text in texts(response))
    assert not web.fake.calls and not ImportRun.objects.exists()


@pytest.mark.django_db
def test_import_page_flow(web):
    from unittest.mock import patch as mock_patch
    for key in range(1, 11):
        web.fake.add(key, start=at(key))
    with web.fake.serving(), mock_patch("garage.services.strava_client.PER_PAGE", 2):
        # One press reads up to four pages (here of 2 activities).
        response = web.client.post(reverse("garage:strava-import"), {"after": "2026-02-01"})
        run = ImportRun.objects.get()
        assert response.status_code == 302 and response["Location"] == reverse("garage:history-run", args=[run.pk])
        page = html(web.client.get(response["Location"]))
        assert "Strava · En pausa" in page and "Paused" not in page
        assert "4 páginas confirmadas" in page and "Continuar importación" in page and "Powered by Strava" in page
        assert 'enctype="multipart/form-data"' not in page, "a Strava job needs no file"
        response = web.client.post(reverse("garage:history-run", args=[run.pk]))
    run.refresh_from_db()
    assert response.status_code == 302 and run.state == "completed" and run.items_imported == 10
    assert "Strava · Completado" in html(web.client.get(reverse("garage:history-run", args=[run.pk])))
    from datetime import datetime
    from zoneinfo import ZoneInfo
    assert run.requested_from == datetime(2026, 2, 1, tzinfo=ZoneInfo("Europe/Madrid")), "a local date in the viewer's zone"
    index = html(web.client.get(reverse("garage:history")))
    assert "Strava ·" in index and "5 pág." in index and reverse("garage:strava") in index and "Completado" in index


@pytest.mark.django_db
def test_import_rejects_future_dates_and_cancel_works(web):
    with web.fake.serving():
        response = web.client.post(reverse("garage:strava-import"), {"after": "2999-01-01"})
    assert response.status_code == 400 and "Elige una fecha pasada." in html(response) and not web.fake.calls
    connected(web)
    run = ImportRun.objects.create(owner=web.owner, source_kind="strava", items_imported=0, items_skipped=0,
                                   requested_from=at())
    response = web.client.post(reverse("garage:history-cancel", args=[run.pk]))
    run.refresh_from_db()
    assert response.status_code == 302 and run.state == "cancelled"


@pytest.mark.django_db
def test_gear_link_form(web):
    connected(web)
    gear = StravaGear.objects.get(owner=web.owner)
    response = web.client.post(reverse("garage:strava-gear", args=[gear.pk]), {f"{gear.pk}-bike": str(web.bike.pk)})
    gear.refresh_from_db()
    assert response.status_code == 302 and gear.bike_id == web.bike.pk
    assert any("cuenta ahora como Gravel de Garage" in text for text in texts(response))
    foreign_bike = create_inventory(web.other, Bike, name="Ajena")
    response = web.client.post(reverse("garage:strava-gear", args=[gear.pk]), {f"{gear.pk}-bike": str(foreign_bike.pk)})
    gear.refresh_from_db()
    assert gear.bike_id == web.bike.pk and any("Elige una de tus bicis." in text for text in texts(response))
    web.client.post(reverse("garage:strava-gear", args=[gear.pk]), {f"{gear.pk}-bike": ""})
    gear.refresh_from_db()
    assert gear.bike_id is None
    foreign = StravaGear.objects.create(owner=web.other, gear_id="b2")
    assert web.client.post(reverse("garage:strava-gear", args=[foreign.pk]), {}).status_code == 404


@pytest.mark.django_db
def test_remove_requires_confirmation(web):
    connected(web)
    store(ns(web), 5, start=at(3))
    response = web.client.post(reverse("garage:strava-remove"), {})
    assert response.status_code == 400 and "Marca la casilla para confirmar." in html(response)
    assert ActivitySource.objects.exists()
    response = web.client.post(reverse("garage:strava-remove"), {"confirm": "on"})
    assert response.status_code == 302 and not ActivitySource.objects.exists() and not Ride.objects.exists()
    assert not StravaAccount.objects.exists() and any("Quitado lo sincronizado" in text for text in texts(response))


@pytest.mark.django_db
def test_ride_screens_show_origin_duplicates_and_actions(web):
    connected(web)
    g = ns(web)
    ride, fit_source = fit(g, at(4))
    store(g, 6, start=at(4))
    store(g, 7, start=at(4))  # duplicate: the ride already has a Strava source
    strava_only = ActivitySource.objects.get(external_id=7)
    detail = html(web.client.get(reverse("garage:usage-ride-detail", args=[ride.pk])))
    for text in ("Archivo FIT y Strava", "Strava · actividad 6", "FIT · sesión 0", "Separar fuente", "Unir con…", "Powered by Strava"):
        assert text in detail, text
    duplicate = html(web.client.get(reverse("garage:usage-ride-detail", args=[strava_only.ride_id])))
    assert "Posible duplicado" in duplicate and "No es un duplicado" in duplicate and "Separar fuente" not in duplicate
    with CaptureQueriesContext(connection) as queries:
        listing = web.client.get(reverse("garage:usage-ride-list"))
    assert listing.status_code == 200 and len(queries) <= 25, len(queries)
    assert "Posible duplicado" in html(listing) and "Archivo FIT y Strava" in html(listing) and "Powered by Strava" in html(listing)
    review = html(web.client.get(reverse("garage:ride-review", args=[ride.pk])))
    assert "Archivo FIT y Strava" in review and "Powered by Strava" in review


@pytest.mark.django_db
def test_merge_separate_and_keep_pages(web):
    connected(web)
    g = ns(web)
    ride, _ = fit(g, at(5))
    store(g, 8, start=at(5))
    store(g, 9, start=at(5) + timedelta(seconds=30))
    duplicate = ActivitySource.objects.get(external_id=9)
    url = reverse("garage:history-source-merge", args=[duplicate.pk])
    with CaptureQueriesContext(connection) as queries:
        response = web.client.get(url)  # the FIT ride already has Strava: nothing can receive it
    # The empty state is rendered; a GET stores no session message (garage-030 review).
    assert response.status_code == 200 and "No hay salidas a menos de 6 horas" in html(response) and not texts(response)
    assert not writes(queries) and "Antes de unir" not in html(response)
    # Separate the first Strava source; then the duplicate can join the FIT ride.
    first = ActivitySource.objects.get(external_id=8)
    sep = reverse("garage:history-source-separate", args=[first.pk])
    assert web.client.post(sep, {}).status_code == 200 and ActivitySource.objects.get(external_id=8).ride_id == ride.pk
    response = web.client.post(sep, {"confirm": "on"})
    first.refresh_from_db()
    assert response.status_code == 302 and first.ride_id != ride.pk
    with CaptureQueriesContext(connection) as queries:
        page = html(web.client.get(url))
    assert not writes(queries) and "Unir con…" in page and str(ride.pk) in page and "coincide" in page
    assert str(first.ride_id) not in page, "a ride with an active Strava source cannot receive another"
    response = web.client.post(url, {"ride": str(ride.pk)})
    duplicate.refresh_from_db()
    assert response.status_code == 302 and duplicate.ride_id == ride.pk and not duplicate.possible_duplicate
    store(g, 10, start=at(6))
    store(g, 11, start=at(6))
    marked = ActivitySource.objects.get(external_id=11)
    assert marked.possible_duplicate
    response = web.client.post(reverse("garage:history-source-keep", args=[marked.pk]))
    marked.refresh_from_db()
    assert response.status_code == 302 and not marked.possible_duplicate
    assert web.client.get(reverse("garage:history-source-keep", args=[marked.pk])).status_code == 405


@pytest.mark.django_db
def test_fit_preview_explains_the_strava_join(web):
    connected(web)
    g = ns(web)
    start = FIT_EPOCH + timedelta(seconds=1_100_000_000)
    store(g, 12, start=start, distance="1234567.9")
    upload = SimpleUploadedFile("synthetic.fit", activity(), content_type="application/octet-stream")
    page = html(web.client.post(reverse("garage:history-preview"), {"file": upload, "time_zone": "UTC"}))
    assert "Se unirá a" in page and str(ActivitySource.objects.get(external_id=12).ride_id) in page
    assert "No se fusionarán automáticamente" not in page


@pytest.mark.django_db
def test_export_is_additive_for_strava(web):
    connected(web)
    g = ns(web)
    ride, _ = fit(g, at(7))
    store(g, 13, start=at(7), gear="b1", sport="GravelRide")
    gear = StravaGear.objects.get(gear_id="b1")
    from .services.strava_sources import link_gear
    link_gear(web.owner, gear.pk, web.bike)
    snapshot = export_snapshot(web.owner)
    tables = snapshot["tables"]
    row = next(row for row in tables["rides"] if row["id"] == str(ride.pk))
    assert row["field_provenance"]["bike"]["kind"] == "strava" and row["bike_id"] == str(web.bike.pk)
    assert row["sport_type"] == "gravel_ride" and row["distance_m"] == "30000.000"
    source = next(row for row in tables["sources"] if row["source_kind"] == "strava")
    assert (source["external_id"], source["gear_id"], source["possible_duplicate"]) == (13, "b1", False)
    assert tables["strava_gear"] == [{"id": str(gear.pk), "created_at": tables["strava_gear"][0]["created_at"],
                                      "updated_at": tables["strava_gear"][0]["updated_at"], "gear_id": "b1",
                                      "name": "Strava Gravel", "retired": False, "bike_id": str(web.bike.pk)}]
    assert "Strava account, tokens and webhook events" in snapshot["omitted"]
    raw = str(snapshot)
    assert "athlete" not in raw and "synthetic-access" not in raw and "scopes" not in raw
    assert {"external_id", "gear_id", "possible_duplicate"} <= set(TABLES["sources"][1]) and "strava_gear" in TABLES
    import io
    import json
    from zipfile import ZipFile
    with ZipFile(io.BytesIO(csv_zip(snapshot))) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert "strava_gear.csv" in archive.namelist()
    assert {"external_id", "gear_id"} <= set(manifest["csv"]["tables"]["sources"]["columns"])
    # A bike whose Strava provenance no longer matches the gear link is rejected like any corrupt provenance.
    StravaGear.objects.filter(pk=gear.pk).update(bike=create_inventory(web.owner, Bike, name="Otra"))
    from .services.export import ExportError
    with pytest.raises(ExportError):
        export_snapshot(web.owner)


@pytest.mark.django_db
def test_strava_values_survive_float_free(web):
    connected(web)
    store(ns(web), 14, start=at(8), distance="12345.678")
    assert Ride.objects.get().distance_m == Decimal("12345.678")


# Review of phases 1–2 (18 oct) -----------------------------------------------------

@pytest.mark.django_db
def test_gear_forms_share_one_bike_query_and_name_their_strava_bike(web):
    connected(web)
    create_inventory(web.owner, Bike, name="Carretera de Garage")

    def page_queries():
        with CaptureQueriesContext(connection) as queries:
            page = html(web.client.get(reverse("garage:strava")))
        return len(queries), page
    one, _ = page_queries()
    for key in range(2, 7):
        StravaGear.objects.create(owner=web.owner, gear_id=f"b{key}", name=f"Strava {key}")
    many, page = page_queries()
    assert many == one, "no query per Strava bike"
    for name in ("Strava Gravel", "Strava 2", "Strava 6"):
        assert f"Bici de Garage para «{name}»" in page, name
    assert page.count("Carretera de Garage</option>") == 6


@pytest.mark.django_db
def test_spanish_states_and_sport_labels(web):
    connected(web)
    for state in ("paused", "completed", "failed"):
        ImportRun.objects.create(owner=web.owner, source_kind="strava", items_imported=0, items_skipped=0, requested_from=at(),
                                 state=state, processed=1 if state == "completed" else 0, cursor=1 if state == "completed" else 0)
    page = html(web.client.get(reverse("garage:strava")))
    assert all(label in page for label in ("En pausa", "Completado", "Con error"))
    assert not any(label in page for label in ("Paused", "Completed", "Failed"))
    g = ns(web)
    store(g, 20, start=at(9), sport="GravelRide")
    ride = ActivitySource.objects.get(external_id=20).ride
    detail = html(web.client.get(reverse("garage:usage-ride-detail", args=[ride.pk])))
    listing = html(web.client.get(reverse("garage:usage-ride-list")))
    assert "· gravel ·" in detail and "· gravel ·" in listing and "gravel_ride" not in detail + listing


@pytest.mark.django_db
def test_merge_page_warns_before_keeping_or_deleting(web):
    from .services.rides import correct_ride, create_manual_ride
    connected(web)
    g = ns(web)
    target = create_manual_ride(web.owner, started_at=at(10, hour=8))
    store(g, 21, start=at(10))
    source = ActivitySource.objects.get(external_id=21)
    url = reverse("garage:history-source-merge", args=[source.pk])
    page = html(web.client.get(url))
    assert "Antes de unir" in page and "se borrará con su uso" in page
    correct_ride(web.owner, source.ride_id, notes="Pinchazo", name="Con Ana")
    with CaptureQueriesContext(connection) as queries:
        page = html(web.client.get(url))
    assert not writes(queries)
    assert "correcciones manuales (Nombre, Notas): se conserva con ellas" in page and "se borrará" not in page
    assert "Se quedará sin inicio confirmado" in page
    response = web.client.post(url, {"ride": str(target.pk)})
    assert response.status_code == 302 and Ride.objects.get(pk=source.ride_id).notes == "Pinchazo"


@pytest.mark.django_db
def test_sync_button_reports_a_hint_failure_and_what_is_pending(web):
    connected(web)
    from .models import StravaEvent
    StravaEvent.objects.create(subscription_id=1, athlete_id=4242, object_type="activity", aspect_type="create", object_id=31,
                               event_time=at())
    web.fake.script("/activities/31", FakeResponse(429))
    with web.fake.serving():
        response = web.client.post(reverse("garage:strava-sync"))
    shown = texts(response)
    assert any("límite de peticiones" in text for text in shown) and not any(text.startswith("Sincronizado") for text in shown)
    assert any("Queda 1 aviso del webhook" in text for text in shown)
    assert StravaAccount.objects.get().last_sync_status == "failed"


# Phase 4 «operación diaria» on Más → Strava: the daily sync setting and the revocation notice.

SYNC_TOKEN = "synthetic-page-token-0123456789-abcdefghij"  # 42 characters, never a real secret
AUTO_ON = "Sincronización automática: configurada. El Worker de Cloudflare la pide cada día a las 9:05 (hora de Madrid)"
AUTO_OFF = "Sincronización automática: no configurada (falta GARAGE_SYNC_TOKEN)."


def page_queries(web):
    with patch("garage.services.strava_client.requests.get") as get, \
         patch("garage.services.strava_client.refresh_access_token") as token, CaptureQueriesContext(connection) as queries:
        response = web.client.get(reverse("garage:strava"))
    get.assert_not_called()
    token.assert_not_called()
    assert response.status_code == 200 and not writes(queries)
    return html(response), len(queries)


@pytest.mark.django_db
@pytest.mark.parametrize("token,shown", [("", AUTO_OFF), ("x" * 31, AUTO_OFF), (SYNC_TOKEN, AUTO_ON), ("y" * 32, AUTO_ON)])
def test_page_says_whether_the_daily_sync_is_configured_never_the_token(web, settings, token, shown):
    connected(web)
    settings.GARAGE_SYNC_TOKEN = token
    page, _ = page_queries(web)
    assert shown in page
    assert (AUTO_OFF in page) is (shown == AUTO_OFF) and (AUTO_ON in page) is (shown == AUTO_ON)
    assert "a partir de la primera sincronización manual" not in page
    if token:
        assert token not in page


@pytest.mark.django_db
def test_daily_sync_line_waits_for_the_first_manual_sync_and_is_only_for_the_owner(web, settings):
    settings.GARAGE_SYNC_TOKEN = SYNC_TOKEN
    page, _ = page_queries(web)
    assert AUTO_ON + ", a partir de la primera sincronización manual." in page, "sync_all never creates the account"
    settings.GARAGE_STRAVA_USER = "strava-other"
    page, _ = page_queries(web)
    assert "Sincronización automática" not in page
    settings.GARAGE_STRAVA_USER = ""
    page, _ = page_queries(web)
    assert "Sincronización automática" not in page


@pytest.mark.django_db
def test_a_revoked_account_shows_since_when_and_the_purge_date_instead_of_the_generic_error(web, settings):
    from datetime import datetime, timezone as datetime_timezone
    connected(web)
    settings.GARAGE_SYNC_TOKEN = SYNC_TOKEN
    revoked = datetime(2026, 3, 1, 10, 0, tzinfo=datetime_timezone.utc)
    StravaAccount.objects.filter(owner=web.owner).update(revoked_at=revoked, last_sync_status="failed",
                                                         last_error_code="unauthorized")
    page, _ = page_queries(web)
    assert ("Strava rechaza el token desde el 1 mar 2026. Renueva STRAVA_REFRESH_TOKEN en Render. Si sigue así, lo "
            "sincronizado desde Strava se borrará automáticamente el 31 mar 2026.") in page
    assert '<p class="pending st-due">' in page
    assert "Strava rechazó el token de Stravagancia" not in page, "one notice, not two"
    # Dates in the viewer's zone (Madrid by default): 23:30 UTC on 28 Feb is already 1 March there.
    StravaAccount.objects.filter(owner=web.owner).update(revoked_at=datetime(2026, 2, 28, 23, 30, tzinfo=datetime_timezone.utc))
    page, _ = page_queries(web)
    assert "rechaza el token desde el 1 mar 2026" in page and "borrará automáticamente el 31 mar 2026" in page
    # Another failure while revoked (e.g. a 429) keeps its own text too.
    StravaAccount.objects.filter(owner=web.owner).update(last_error_code="rate_limited")
    page, _ = page_queries(web)
    assert "rechaza el token desde el" in page and "Reintenta en 15 minutos" in page


@pytest.mark.django_db
@pytest.mark.parametrize("revoked_at,since,purge", [
    ("2026-10-10T22:30:00+00:00", "11 oct 2026", "10 nov 2026"),  # 00:30 CEST: the 30th Madrid day, not 9 nov (UTC + 30 d)
    ("2026-10-10T07:05:20+00:00", "10 oct 2026", "9 nov 2026"),   # the daily run of 9 nov (09:05 CET) purges
    ("2026-03-20T08:05:20+00:00", "20 mar 2026", "19 abr 2026"),  # across the start of summer time
])
def test_the_purge_date_shown_is_the_day_the_daily_run_purges(web, settings, revoked_at, since, purge):
    """Review of phase 4: the date comes from strava_sync.purge_date, the rule sync_all applies (Madrid days)."""
    from datetime import date, datetime
    from .services.strava_sync import purge_date
    connected(web)
    settings.GARAGE_SYNC_TOKEN = SYNC_TOKEN
    instant = datetime.fromisoformat(revoked_at)
    StravaAccount.objects.filter(owner=web.owner).update(revoked_at=instant, last_error_code="unauthorized")
    page, _ = page_queries(web)
    assert f"rechaza el token desde el {since}." in page and f"se borrará automáticamente el {purge}." in page
    day, month, year = purge.split()
    assert purge_date(instant) == date(int(year), {"mar": 3, "abr": 4, "oct": 10, "nov": 11}[month], int(day))


@pytest.mark.django_db
@pytest.mark.parametrize("token", ["", "x" * 31])
def test_without_the_daily_sync_the_notice_promises_no_automatic_purge(web, settings, token):
    """Review of phase 4: without GARAGE_SYNC_TOKEN nothing calls sync-all, so nothing is purged by itself."""
    from datetime import datetime, timezone as datetime_timezone
    connected(web)
    settings.GARAGE_SYNC_TOKEN = token
    StravaAccount.objects.filter(owner=web.owner).update(revoked_at=datetime(2026, 3, 1, 10, 0, tzinfo=datetime_timezone.utc),
                                                         last_error_code="unauthorized")
    page, _ = page_queries(web)
    assert ("Si sigue así, lo sincronizado desde Strava se borrará en la primera sincronización diaria a partir del "
            "31 mar 2026; sin sincronización automática, sólo si alguien ejecuta manage.py garage_strava_sync.") in page
    assert "automáticamente el" not in page and AUTO_OFF in page


@pytest.mark.django_db
def test_without_revocation_or_for_another_owner_there_is_no_purge_notice(web, settings):
    connected(web)
    StravaAccount.objects.filter(owner=web.owner).update(last_sync_status="failed", last_error_code="unauthorized")
    page, _ = page_queries(web)
    assert "rechaza el token desde" not in page and "Strava rechazó el token de Stravagancia" in page
    StravaAccount.objects.filter(owner=web.owner).update(revoked_at=at(1))
    settings.GARAGE_STRAVA_USER = "strava-other"  # the daily sync would not purge this account: no date promised
    page, _ = page_queries(web)
    assert "se borrará" not in page and "Strava rechazó el token de Stravagancia" in page


@pytest.mark.django_db
def test_a_persistent_401_from_the_button_shows_the_revocation_on_the_page(web):
    connected(web)
    web.fake.script("/athlete", FakeResponse(401), FakeResponse(401))
    with web.fake.serving():
        web.client.post(reverse("garage:strava-sync"))
    assert StravaAccount.objects.get().revoked_at is not None
    page, _ = page_queries(web)
    assert "Strava rechaza el token desde el" in page and "Renueva STRAVA_REFRESH_TOKEN en Render" in page


@pytest.mark.django_db
def test_the_phase_4_texts_add_no_query_script_or_inline_style(web, settings):
    connected(web)
    _, plain = page_queries(web)
    settings.GARAGE_SYNC_TOKEN = SYNC_TOKEN
    StravaAccount.objects.filter(owner=web.owner).update(revoked_at=at(1), last_error_code="unauthorized")
    page, revoked = page_queries(web)
    assert "rechaza el token desde" in page and AUTO_ON in page
    assert revoked == plain <= 20, (plain, revoked)
    assert "<script>" not in page and " style=" not in page and "onclick=" not in page
