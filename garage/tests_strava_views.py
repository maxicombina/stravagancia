"""Más → Strava, ride source screens and export (garage-030). GET never writes nor calls Strava."""
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.contrib.messages import get_messages
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .importers.fit import FIT_EPOCH
from .models import (ActivitySource, Bike, Category, ImportRun, Installation, Item, MaintenanceRule, Ride, ServiceEvent, ServiceType,
                     StravaAccount, StravaGear)
from .services.export import TABLES, csv_zip, export_snapshot
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .services.rides import create_manual_ride
from .services.snoozes import snooze_rule
from .services.usage_profiles import create_profile, revise_profile
from .test_html import find_all, parse, visible_text
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


def strava_page(web):
    return parse(html(web.client.get(reverse("garage:strava"))))


def section_of(page, title):
    sections = find_all(page, "section", aria_labelledby=title)
    assert len(sections) == 1, title
    return sections[0]


def classes(node):
    return set(node.attrs["class"].split())


def connected_chips(page):
    return [chip for chip in find_all(page, cls="chip") if "Conectado" in visible_text(chip)]


@pytest.mark.django_db
def test_syncing_is_the_main_action_and_importing_the_quiet_one(web):
    # The mockup: «Sincronizar ahora», primary and with its icon; «Importar histórico», which is done once, in ghost with a download icon.
    connected(web)
    page = strava_page(web)
    def button_of(section):
        buttons = find_all(section_of(page, section), "button", type="submit")
        assert len(buttons) == 1, section
        return buttons[0]
    sync, history = button_of("strava-state"), button_of("strava-import")
    assert classes(sync) == {"btn"} and [use.attrs["href"] for use in find_all(sync, "use")] == ["#i-sync"]
    assert classes(history) == {"btn", "ghost"} and [use.attrs["href"] for use in find_all(history, "use")] == ["#i-download"]
    assert visible_text(sync) == "Sincronizar ahora" and visible_text(history) == "Importar histórico"
    assert find_all(page, "symbol", id="i-sync")


@pytest.mark.django_db
def test_the_state_panel_says_connected_in_its_header(web):
    """Spec garage-050 §5, `strava.html`: «`.panel` Estado; chip "Conectado" si procede», as in the mockup."""
    connected(web)
    panel = section_of(strava_page(web), "strava-state")
    assert "panel" in classes(panel)
    heads = find_all(panel, cls="sec-h")
    assert len(heads) == 1 and visible_text(find_all(heads[0], "h2", id="strava-state")[0]) == "Estado"
    chips = connected_chips(heads[0])
    assert len(chips) == 1 and {"chip", "st-ok"} <= classes(chips[0]) and visible_text(chips[0]) == "Conectado"
    # The color never goes alone (spec §4.2): an icon and a word.
    assert [use.attrs["href"] for use in find_all(chips[0], "use")] == ["#i-check"]
    assert find_all(chips[0], "svg", aria_hidden="true")


@pytest.mark.django_db
@pytest.mark.parametrize("changes,says", [
    ({"revoked_at": at(1), "last_sync_status": "failed", "last_error_code": "unauthorized"}, "Strava rechaza el token"),
    ({"last_sync_status": "failed", "last_error_code": "unauthorized"}, "Strava rechazó el token"),
    ({"last_sync_status": "failed", "last_error_code": "rate_limited"}, "Strava pide esperar"),
    ({"last_sync_status": "failed", "last_error_code": "network"}, "No se pudo hablar con Strava"),
])
def test_no_connected_chip_beside_a_failure(web, changes, says):
    connected(web)
    StravaAccount.objects.filter(owner=web.owner).update(**changes)
    panel = section_of(strava_page(web), "strava-state")
    assert says in visible_text(panel) and not connected_chips(panel)


@pytest.mark.django_db
def test_no_connected_chip_before_the_first_sync(web):
    panel = section_of(strava_page(web), "strava-state")
    assert "Todavía sin sincronizar" in visible_text(panel) and not connected_chips(panel)


@pytest.mark.django_db
def test_no_connected_chip_for_an_account_that_does_not_sync(web, settings):
    connected(web)
    settings.GARAGE_STRAVA_USER = web.other.username
    page = strava_page(web)
    assert "Esta cuenta no sincroniza" in visible_text(page) and not connected_chips(page)


@pytest.mark.django_db
def test_a_sync_that_skipped_activities_is_still_connected(web):
    connected(web)
    StravaAccount.objects.filter(owner=web.owner).update(last_sync_status="partial", last_error_code="")
    assert len(connected_chips(section_of(strava_page(web), "strava-state"))) == 1


@pytest.mark.django_db
@pytest.mark.parametrize("title", ["strava-import", "strava-gear", "strava-remove"])
def test_each_section_of_strava_is_a_card(web, title):
    connected(web)
    section = section_of(strava_page(web), title)
    assert {"sec", "card"} <= classes(section) and find_all(section, "h2", id=title)


@pytest.mark.django_db
def test_no_surface_of_strava_holds_another(web):
    connected(web)
    page = strava_page(web)
    surfaces = find_all(page, cls="card") + find_all(page, cls="panel")
    assert len(surfaces) == 4
    for surface in surfaces:
        assert not find_all(surface, cls="card") and not find_all(surface, cls="panel"), surface


@pytest.mark.django_db
def test_each_bike_of_strava_keeps_its_own_form(web):
    connected(web)
    StravaGear.objects.create(owner=web.owner, gear_id="b2", name="Strava 2")
    forms = find_all(section_of(strava_page(web), "strava-gear"), "form", cls="form")
    assert {form.attrs["action"] for form in forms} == {reverse("garage:strava-gear", args=[gear.pk]) for gear in StravaGear.objects.filter(owner=web.owner)}
    assert len(forms) == 2
    for form in forms:
        assert len(find_all(form, "select")) == 1 and [visible_text(button) for button in find_all(form, "button")] == ["Guardar vínculo"]


@pytest.mark.django_db
def test_without_bikes_of_strava_the_card_says_so(web):
    section = section_of(strava_page(web), "strava-gear")
    assert "card" in classes(section) and "Todavía no hay bicis de Strava" in visible_text(section)


@pytest.mark.django_db
def test_the_danger_zone_is_a_card_and_its_button_says_it_deletes(web):
    connected(web)
    zone = section_of(strava_page(web), "strava-remove")
    assert "danger-zone" in classes(zone)
    assert [visible_text(button) for button in find_all(zone, "button", cls="btn danger")] == ["Quitar lo sincronizado"]


@pytest.mark.django_db
def test_powered_by_strava_stays_outside_the_cards(web):
    connected(web)
    page = strava_page(web)
    notes = [note for note in find_all(page, "p", cls="note") if visible_text(note) == "Powered by Strava"]
    assert len(notes) == 1
    for surface in find_all(page, cls="card") + find_all(page, cls="panel"):
        assert notes[0] not in find_all(surface, "p", cls="note")


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
def test_the_loose_actions_of_a_source_are_all_controls_for_a_finger(web):
    # They are not inside a sentence: beside them, «Retirar» and «No es un duplicado» already measure 44 px, and these measured 30.
    connected(web)
    g = ns(web)
    ride, _ = fit(g, at(4))
    store(g, 6, start=at(4))
    store(g, 7, start=at(4))  # a duplicate: on its own ride, with «No es un duplicado»
    duplicate = ActivitySource.objects.get(external_id=7)
    links, buttons = [], []
    for pk in (ride.pk, duplicate.ride_id):
        root = parse(html(web.client.get(reverse("garage:usage-ride-detail", args=[pk]))))
        sections = find_all(root, "section", aria_labelledby="sources-title")
        assert len(sections) == 1
        links += find_all(sections[0], "a")
        buttons += find_all(sections[0], "button")
    assert {visible_text(link) for link in links} == {"Separar fuente", "Unir con…", "Retirar"}
    assert {visible_text(button) for button in buttons} == {"No es un duplicado"}
    assert {(visible_text(link), link.attrs["class"]) for link in links if "solo" not in link.attrs["class"].split()} == set()
    assert all("link-btn" in button.attrs["class"].split() for button in buttons)


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
def test_withdrawing_a_source_has_room_for_a_finger(web):
    # Alone in the last cell of its row, it measured 33.8 px: the 44 px of `.link.solo`, as the other links that stand alone.
    connected(web)
    ride, source = fit(ns(web), at(4))
    page = parse(html(web.client.get(reverse("garage:usage-ride-detail", args=[ride.pk]))))
    rows = [row for row in find_all(page, "li", cls="entry compact") if "FIT · sesión 0" in visible_text(row)]
    assert len(rows) == 1
    links = [child for child in rows[0].children if not isinstance(child, str) and child.tag == "a"]
    assert [(visible_text(link), set(link.attrs["class"].split()), link.attrs["href"]) for link in links] == [
        ("Retirar", {"link", "solo"}, reverse("garage:history-source-withdraw", args=[source.pk]))]


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


SECONDS = datetime(2026, 10, 17, 10, 7, 30, 123456, tzinfo=dt_timezone.utc)  # 12:07:30,123456 in Madrid
MICROSECONDS = re.compile(r"\d:\d{2}:\d{2},\d{6}")


def stamped_by_the_server(web, clock=None):
    """What the server stamps with `now()` (garage-047 F22, R2-03): a sync, a Strava job, a snooze, a usage profile «desde ahora» and
    its next version, also «desde ahora». With `clock` (a one-element list read by `now()`), the next version is a day and 7 s later."""
    with web.fake.serving():
        assert web.client.post(reverse("garage:strava-sync")).status_code == 302
        assert web.client.post(reverse("garage:strava-import"), {"after": "2026-02-01"}).status_code == 302
    category = create_inventory(web.owner, Category, name="Bidones")
    bottle = create_inventory(web.owner, Item, name="Bidón", category=category)
    kind = save_maintenance(web.owner, ServiceType, name="Limpieza")
    rule = save_maintenance(web.owner, MaintenanceRule, item=bottle, service_type=kind, calendar_days=30,
                            anchor_at=timezone.now().replace(second=0, microsecond=0) - timedelta(days=5))
    snooze_rule(web.owner, rule, calendar_days=10)
    profile = create_profile(web.owner, name="Ahora", items=[bottle])
    if clock is not None:
        clock[0] += timedelta(days=1, seconds=7)
    revised = revise_profile(web.owner, profile.pk, items=[bottle])
    return SimpleNamespace(bottle=bottle, rule=rule, profile=profile, revised=revised, run=ImportRun.objects.get(owner=web.owner))


def page_text(web, name, *args):
    response = web.client.get(reverse(name, args=args))
    assert response.status_code == 200, name
    return visible_text(parse(html(response)))


@pytest.mark.django_db
def test_server_times_are_to_the_minute(web, monkeypatch):
    """Strava, «Histórico propio», the Taller and the usage profile show what `now()` stamped to the minute: «12:07», not «12:07:30,123456»."""
    clock = [SECONDS]
    monkeypatch.setattr("django.utils.timezone.now", lambda: clock[0])
    stamped = stamped_by_the_server(web, clock)
    strava = page_text(web, "garage:strava")
    assert "Última sincronización: 17 oct 2026, 12:07 · " in strava and "17 oct 2026, 12:07 · desde 1 feb 2026" in strava
    assert "Strava · 17 oct 2026, 12:07" in page_text(web, "garage:history")
    assert "Aplazamiento desde el 17 oct 2026, 12:07: 10 días · activo." in page_text(web, "garage:maintenance")
    profile = page_text(web, "garage:usage-profile-detail", stamped.profile.pk)
    assert "17 oct 2026, 12:07 → 18 oct 2026, 12:07" in profile and "18 oct 2026, 12:07 → sin final" in profile
    for text in (strava, page_text(web, "garage:history"), page_text(web, "garage:maintenance"), profile):
        assert not MICROSECONDS.search(text) and "12:07:30" not in text and "12:07:37" not in text
    exact = html(web.client.get(reverse("garage:usage-profile-detail", args=[stamped.profile.pk])))
    assert 'datetime="2026-10-17T10:07:30.123456Z"' in exact and 'datetime="2026-10-18T10:07:37.123456Z"' in exact


@pytest.mark.django_db
def test_no_screen_shows_microseconds(web):
    """Guard (R2-03), with data of the tests and the real `now()`: no screen shows an hour with microseconds. The rides, the rule and
    the intervention keep whole minutes or seconds, as a person or a source writes them; what the server stamps keeps its microseconds."""
    stamped = stamped_by_the_server(web)
    owner, bike, bottle = web.owner, web.bike, stamped.bottle
    minute = timezone.now().replace(second=0, microsecond=0)
    create_installation(owner, item=bottle, bike=bike, parent_item=None, started_at=minute - timedelta(days=40), ended_at=None, slot=None)
    rides = [create_manual_ride(owner, started_at=minute - timedelta(days=day, seconds=17), bike=bike, name=f"Ruta {day}",
                                distance_m=Decimal(42000), moving_time_s=Decimal(5400)) for day in (2, 9, 30)]
    kind = save_maintenance(owner, ServiceType, name="Engrase")
    due = save_maintenance(owner, MaintenanceRule, item=bottle, service_type=kind, distance_m=Decimal(50000), anchor_at=minute - timedelta(days=35))
    event = save_maintenance(owner, ServiceEvent, item=bottle, service_type=kind, performed_at=minute - timedelta(days=20), amount=Decimal("12.5"), currency="EUR")
    loose = create_inventory(owner, Item, name="Suelta", category=bottle.category)
    mount = Installation.objects.get(item=bottle, ended_at__isnull=True)
    pages = [
        # The 12 screens of the captures (§8)…
        ("garage:index",), ("garage:usage-ride-list",), ("garage:maintenance",), ("garage:statistics",), ("garage:more",),
        ("garage:bike-detail", bike.pk), ("garage:item-detail", bottle.pk), ("garage:item-list",), ("garage:service-event-create",),
        ("garage:strava",),
        # …«Histórico propio», the page of the job, the usage profile, and the extra screens of the blocks.
        ("garage:history",), ("garage:history-run", stamped.run.pk), ("garage:usage-profile-detail", stamped.profile.pk),
        ("garage:usage-profile-detail", stamped.revised.pk), ("garage:usage-profile-list",), ("garage:usage-profile-create",),
        ("garage:usage-ride-detail", rides[0].pk), ("garage:history-manual-create",), ("garage:bike-list",), ("garage:category-list",),
        ("garage:item-create",), ("garage:item-used-create",), ("garage:service-type-create",), ("garage:maintenance-rule-create",),
        ("garage:maintenance-rule-edit", due.pk), ("garage:maintenance-rule-snooze", stamped.rule.pk), ("garage:service-event-detail", event.pk),
        ("garage:installation-create", loose.pk), ("garage:installation-replace", mount.pk), ("garage:installation-transfer", mount.pk),
        ("garage:baseline-create", bottle.pk), ("garage:item-lifespan", bottle.pk), ("garage:item-retire", bottle.pk), ("garage:bike-retire", bike.pk),
        ("garage:export",),
    ]
    shown = {}
    for name, *args in pages:
        response = web.client.get(reverse(name, args=args))
        assert response.status_code == 200, name
        shown[(name, *args)] = html(response)
    for query in ("?period=all", "?period=year", f"?bike={bike.pk}"):
        url = reverse("garage:statistics" if "period" in query else "garage:usage-ride-list") + query
        response = web.client.get(url)
        assert response.status_code == 200, url
        shown[url] = html(response)
    anonymous = Client()
    for name in ("garage:offline",):
        shown[name] = html(anonymous.get(reverse(name)))
    shown["login"] = html(anonymous.get(reverse("login") + "?next=/garage/"))
    assert {key: MICROSECONDS.search(page).group(0) for key, page in shown.items() if MICROSECONDS.search(page)} == {}
    # Not vacuous: the server's instants do have microseconds, and they stay exact in `datetime`.
    account = StravaAccount.objects.get(owner=owner)
    assert account.last_sync_at.microsecond == 0 or re.search(r'datetime="[^"]+\.\d{6}Z"', shown[("garage:strava",)])


# garage-047 F21 (D24): one unfinished Strava job at a time, and a warning before repeating a date a recent one covers.

BLOCKED = "Ya hay un trabajo de importación sin terminar: continúalo aquí o cancélalo para empezar otro."
MADRID = ZoneInfo("Europe/Madrid")
FEB_1 = datetime(2026, 2, 1, tzinfo=MADRID)  # what «Importar histórico desde 1 feb 2026» asks for, seen from Madrid


def connected_quietly(web, since=timedelta(days=30)):
    """The owner's account, connected `since` ago; what Strava was asked to connect it is forgotten."""
    account = connected(web)
    StravaAccount.objects.filter(pk=account.pk).update(connected_at=timezone.now() - since)
    web.fake.calls.clear()
    web.fake.tokens = 0
    return account


def strava_job(web, state, *, since=FEB_1, finished=None, created=None, owner=None, kind="strava"):
    """A job in `state` asking from `since`. `finished` and `created` stamp `updated_at` and `created_at`; with `finished` alone, it was
    created an hour before it finished; with `created` alone, it was not saved again after it was created."""
    done = state == "completed"
    values = {"items_imported": 0, "items_skipped": 0} if kind == "strava" else {}
    run = ImportRun.objects.create(owner=owner or web.owner, source_kind=kind, requested_from=since, state=state,
                                   processed=1 if done else 0, cursor=1 if done else 0, **values)
    if finished is not None and created is None:
        created = finished - timedelta(hours=1)
    if created is not None and finished is None:
        finished = created
    stamps = {name: value for name, value in (("updated_at", finished), ("created_at", created)) if value is not None}
    if stamps:
        ImportRun.objects.filter(pk=run.pk).update(**stamps)
        run.refresh_from_db()
    return run


def press_import(web, after="2026-02-01", **extra):
    """«Importar histórico» from `after`, with Strava answering (an empty history); what it was asked stays in web.fake."""
    with web.fake.serving():
        return web.client.post(reverse("garage:strava-import"), {"after": after, **extra})


def asked_strava(web):
    return bool(web.fake.calls or web.fake.tokens)


def created_one_more(response, before):
    """The press created one job, and led to it."""
    new = ImportRun.objects.exclude(pk__in=[run.pk for run in before]).get()
    assert response.status_code == 302 and response["Location"] == reverse("garage:history-run", args=[new.pk]), response.status_code
    return new


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["pending", "running", "paused", "failed"])
def test_an_unfinished_run_blocks_a_new_one(web, state):
    connected_quietly(web)
    run = strava_job(web, state)
    response = press_import(web)
    assert response.status_code == 302 and response["Location"] == reverse("garage:history-run", args=[run.pk])
    assert texts(response) == [BLOCKED]
    assert list(ImportRun.objects.all()) == [run] and not asked_strava(web)


@pytest.mark.django_db
def test_with_two_unfinished_runs_the_block_leads_to_the_most_recent(web):
    """Only from before garage-047 can two be unfinished at once. Created in the other order, to tell «most recent» from «last inserted»."""
    connected_quietly(web)
    newer = strava_job(web, "paused", created=timezone.now() - timedelta(days=1))
    strava_job(web, "failed", created=timezone.now() - timedelta(days=3))
    response = press_import(web)
    assert response.status_code == 302 and response["Location"] == reverse("garage:history-run", args=[newer.pk])
    assert ImportRun.objects.count() == 2 and not asked_strava(web)


@pytest.mark.django_db
def test_the_service_returns_the_unfinished_run(web):
    from .services.strava_sync import UnfinishedImport, start_strava_import
    for key in range(1, 4):
        web.fake.add(key, start=at(key))
    with web.fake.serving(), patch("garage.services.strava_client.PER_PAGE", 2):
        first = start_strava_import(web.owner, after=at(1) - timedelta(days=1))
        assert first.state == "paused"
        asked = (len(web.fake.calls), web.fake.tokens)
        with pytest.raises(UnfinishedImport) as raised:
            start_strava_import(web.owner, after=at(1) - timedelta(days=1))
    assert raised.value.run == first and ImportRun.objects.count() == 1
    assert (len(web.fake.calls), web.fake.tokens) == asked, "the second call asked Strava nothing"


@pytest.mark.django_db
def test_without_an_account_an_unfinished_job_does_not_block(web):
    """«Quitar lo sincronizado» (or the daily purge) deletes the account and the rides and keeps the jobs: an unfinished one is
    from a connection whose rides are gone, and continuing it would skip its confirmed pages. A new job starts from page 1."""
    from .services.strava_sync import start_strava_import
    web.fake.add(1, start=at(1))
    left = strava_job(web, "paused", since=at(1) - timedelta(days=1))
    ImportRun.objects.filter(pk=left.pk).update(cursor=1, processed=1)
    with web.fake.serving():
        run = start_strava_import(web.owner, after=at(1) - timedelta(days=1))
    assert run != left and run.state == "completed" and Ride.objects.filter(owner=web.owner).count() == 1
    assert [(call.path, call.params.get("page")) for call in web.fake.calls] == [("/athlete", None), ("/athlete/activities", 1)]


@pytest.mark.django_db
def test_importing_again_after_removing_the_data_brings_every_ride_back(web):
    """B14-R1-01: a job paused before «Quitar lo sincronizado» led the next press to «Continuar», which asked only from its
    cursor on: the rides of its confirmed pages never came back, and the job then said «Completado»."""
    from .services.strava_sources import remove_strava_data
    from .services.strava_sync import start_strava_import
    for key in range(1, 5):
        web.fake.add(key, start=at(key))
    with patch("garage.services.strava_client.PER_PAGE", 2):
        with web.fake.serving():
            first = start_strava_import(web.owner, after=at(1) - timedelta(days=1), budget=1)
        assert first.state == "paused" and first.cursor == 1 and Ride.objects.filter(owner=web.owner).count() == 2
        remove_strava_data(web.owner)
        assert not Ride.objects.filter(owner=web.owner).exists() and not StravaAccount.objects.exists()
        assert "sin terminar" not in visible_text(strava_page(web)), "the Strava page points to no job"
        web.fake.calls.clear()
        response = press_import(web, after="2026-02-27")
    new = created_one_more(response, [first])
    assert BLOCKED not in texts(response)
    assert [call.params["page"] for call in web.fake.calls if call.path == "/athlete/activities"] == [1, 2, 3]
    assert new.state == "completed" and Ride.objects.filter(owner=web.owner).count() == 4


@pytest.mark.django_db
def test_a_job_from_an_earlier_connection_neither_blocks_nor_is_pointed_to(web):
    """As after «Quitar lo sincronizado» and a «Sincronizar ahora» that connected again: the paused job is from before."""
    connected_quietly(web, since=timedelta(days=1))
    left = strava_job(web, "paused", created=timezone.now() - timedelta(days=2))
    assert "sin terminar" not in visible_text(strava_page(web))
    created_one_more(press_import(web), [left])


@pytest.mark.django_db
@pytest.mark.parametrize("earlier, blocks", [(timedelta(0), True), (timedelta(microseconds=1), False)])
def test_the_edge_of_the_current_connection(web, monkeypatch, earlier, blocks):
    """A job created, and not saved since, at the very instant of the connection is of it; one a microsecond before is not."""
    monkeypatch.setattr("django.utils.timezone.now", lambda: SECONDS)
    account = connected_quietly(web, since=timedelta(days=1))
    account.refresh_from_db()
    run = strava_job(web, "paused", created=account.connected_at - earlier)
    response = press_import(web)
    if blocks:
        assert response.status_code == 302 and response["Location"] == reverse("garage:history-run", args=[run.pk])
        assert texts(response) == [BLOCKED] and ImportRun.objects.count() == 1 and not asked_strava(web)
    else:
        created_one_more(response, [run])


@pytest.mark.django_db
def test_a_job_continued_under_the_new_connection_blocks_a_second_one(web):
    """B14-R2-01: after «Quitar lo sincronizado», «Continuar importación» on the old paused job connects again (a connection
    later than the job) and the job asks Strava and pauses again. It is unfinished under the current connection: D24, the
    Strava page points to it and neither the view nor the service creates a second job."""
    from .services.strava_sources import remove_strava_data
    from .services.strava_sync import UnfinishedImport, start_strava_import
    since = datetime(2026, 2, 27, tzinfo=MADRID)
    for key in range(1, 13):
        web.fake.add(key, start=at(key))
    with patch("garage.services.strava_client.PER_PAGE", 2):
        with web.fake.serving():
            job = start_strava_import(web.owner, after=since, budget=1)
        assert job.state == "paused" and job.cursor == 1
        remove_strava_data(web.owner)
        with web.fake.serving():
            assert web.client.post(reverse("garage:history-run", args=[job.pk])).status_code == 302  # «Continuar importación»
        job.refresh_from_db()
        assert job.state == "paused" and job.cursor > 1, (job.state, job.cursor)
        assert StravaAccount.objects.get(owner=web.owner).connected_at > job.created_at
        notes = [visible_text(note) for note in find_all(strava_page(web), "p", cls="pending") if "sin terminar" in visible_text(note)]
        assert notes == ["Hay un trabajo sin terminar desde el 27 feb 2026: continúalo."]
        web.fake.calls.clear()
        web.fake.tokens = 0
        response = press_import(web, after="2026-01-01")
        assert response.status_code == 302 and response["Location"] == reverse("garage:history-run", args=[job.pk])
        assert texts(response) == [BLOCKED]
        with web.fake.serving(), pytest.raises(UnfinishedImport) as raised:  # the service's own guard, past the view's
            start_strava_import(web.owner, after=since)
    assert raised.value.run == job and list(ImportRun.objects.all()) == [job] and not asked_strava(web)


def made_meanwhile(web):
    """Another press connects and creates its job while this one waits for Strava's athlete: the race the lock that creates a
    job settles. The other press's job comes after its account, as start_strava_import always makes it."""
    original, made = web.fake.get, []

    def meanwhile(url, **kwargs):
        if not made:
            StravaAccount.objects.create(owner=web.owner, athlete_id=web.fake.athlete_id)
            made.append(strava_job(web, "running"))
        return original(url, **kwargs)
    web.fake.get = meanwhile
    return made


@pytest.mark.django_db
def test_a_run_created_while_strava_answers_is_returned_not_doubled(web):
    from .services.strava_sync import UnfinishedImport, start_strava_import
    made = made_meanwhile(web)
    with web.fake.serving(), pytest.raises(UnfinishedImport) as raised:
        start_strava_import(web.owner, after=at(1))
    assert raised.value.run == made[0] and ImportRun.objects.count() == 1
    assert web.fake.paths() == ["/athlete"], "no page of activities was asked for"


@pytest.mark.django_db
def test_the_page_leads_to_a_run_created_while_strava_answers(web):
    made = made_meanwhile(web)
    response = press_import(web)
    assert response.status_code == 302 and response["Location"] == reverse("garage:history-run", args=[made[0].pk])
    assert texts(response) == [BLOCKED] and ImportRun.objects.count() == 1


@pytest.mark.django_db
def test_a_recently_covered_date_asks_for_confirmation(web):
    connected_quietly(web)
    covering = strava_job(web, "completed", since=datetime(2026, 1, 10, tzinfo=MADRID), finished=timezone.now() - timedelta(days=2))
    response = press_import(web)
    assert response.status_code == 400 and list(ImportRun.objects.all()) == [covering] and not asked_strava(web)
    page = parse(html(response))
    assert "Ya importaste el histórico desde el 10 ene 2026 (trabajo completado el " in visible_text(page)
    assert ("). Repetirlo no duplica salidas, pero gasta cuota de Strava; para traer las nuevas basta «Sincronizar ahora». "
            "Si aun así quieres repetirlo, marca «Importar de nuevo igualmente».") in visible_text(page)
    boxes = find_all(page, "input", name="again")
    assert [(box.attrs["type"], "checked" in box.attrs) for box in boxes] == [("checkbox", False)]
    assert not texts(response)
    created_one_more(press_import(web, again="on"), [covering])


@pytest.mark.django_db
def test_the_box_appears_only_with_the_warning(web):
    connected_quietly(web)
    assert not find_all(parse(html(web.client.get(reverse("garage:strava")))), "input", name="again")
    strava_job(web, "completed", finished=timezone.now() - timedelta(days=2))
    assert not find_all(parse(html(web.client.get(reverse("garage:strava")))), "input", name="again")
    rejected = press_import(web, after="2999-01-01")
    assert rejected.status_code == 400 and not find_all(parse(html(rejected)), "input", name="again")


@pytest.mark.django_db
def test_the_warning_gives_a_date_and_a_time_to_the_minute(web, monkeypatch):
    monkeypatch.setattr("django.utils.timezone.now", lambda: SECONDS)
    connected_quietly(web)
    strava_job(web, "completed", finished=SECONDS - timedelta(days=2))  # 15 oct 2026, 12:07:30,123456 in Madrid
    text = visible_text(parse(html(press_import(web))))
    assert "Ya importaste el histórico desde el 1 feb 2026 (trabajo completado el 15 oct 2026, 12:07). Repetirlo" in text
    assert not MICROSECONDS.search(text) and "12:07:30" not in text


@pytest.mark.django_db
def test_the_warning_cites_the_most_recently_completed_job(web, monkeypatch):
    """B14-R1-02: two completed jobs cover 1 Feb. The warning cites the one that finished last, which was created first:
    neither the first finished nor the last created."""
    monkeypatch.setattr("django.utils.timezone.now", lambda: SECONDS)
    connected_quietly(web)
    strava_job(web, "completed", since=FEB_1, created=SECONDS - timedelta(days=10), finished=SECONDS - timedelta(days=1))
    strava_job(web, "completed", since=datetime(2026, 1, 1, tzinfo=MADRID), created=SECONDS - timedelta(days=6),
               finished=SECONDS - timedelta(days=5))
    text = visible_text(parse(html(press_import(web))))
    assert re.findall(r"Ya importaste el histórico desde el (.+?) \(trabajo completado el (.+?)\)\.", text) == [
        ("1 feb 2026", "16 oct 2026, 12:07")]


@pytest.mark.django_db
def test_an_unfinished_run_wins_over_the_coverage_warning(web):
    """R2-08: a completed job from two days ago covers the date, and a later one, from an earlier date, is paused."""
    connected_quietly(web)
    covering = strava_job(web, "completed", finished=timezone.now() - timedelta(days=2))
    paused = strava_job(web, "paused", since=datetime(2025, 6, 1, tzinfo=MADRID), created=timezone.now() - timedelta(days=1))
    for extra in ({}, {"again": "on"}):
        response = press_import(web, **extra)
        assert response.status_code == 302 and response["Location"] == reverse("garage:history-run", args=[paused.pk]), extra
        shown = visible_text(parse(html(web.client.get(response["Location"]))))  # and the message is read there
        assert BLOCKED in shown and "Ya importaste" not in shown, extra
    assert set(ImportRun.objects.all()) == {covering, paused} and not asked_strava(web)


@pytest.mark.django_db
def test_the_strava_page_points_to_the_unfinished_run(web):
    connected_quietly(web)
    strava_job(web, "completed", finished=timezone.now() - timedelta(days=2))
    strava_job(web, "cancelled", created=timezone.now() - timedelta(days=1))

    def section():
        page = parse(html(web.client.get(reverse("garage:strava"))))
        return [found for found in find_all(page, "section") if found.attrs.get("aria-labelledby") == "strava-import"][0]
    assert "sin terminar" not in visible_text(section())
    run = strava_job(web, "paused")
    found = section()
    notes = [note for note in find_all(found, "p", cls="pending") if "sin terminar" in visible_text(note)]
    assert [visible_text(note) for note in notes] == ["Hay un trabajo sin terminar desde el 1 feb 2026: continúalo."]
    assert [(link.attrs["href"], visible_text(link)) for link in find_all(notes[0], "a")] == [
        (reverse("garage:history-run", args=[run.pk]), "continúalo")]
    blocks = [child for child in found.children if not isinstance(child, str)]
    assert blocks.index(notes[0]) < blocks.index(find_all(found, "form")[0]), "above the form"


# Guards: what neither blocks nor asks (they pass before garage-047 F21, which neither blocked nor asked anything).

@pytest.mark.django_db
def test_an_earlier_date_needs_no_confirmation(web):
    connected_quietly(web)
    covering = strava_job(web, "completed", finished=timezone.now() - timedelta(days=2))
    created_one_more(press_import(web, after="2026-01-31"), [covering])


@pytest.mark.django_db
def test_a_cancelled_run_does_not_block(web):
    connected_quietly(web)
    cancelled = strava_job(web, "cancelled", created=timezone.now() - timedelta(hours=1))
    created_one_more(press_import(web), [cancelled])


@pytest.mark.django_db
def test_a_run_completed_long_ago_needs_no_confirmation(web):
    from .services.strava_sync import SYNC_DAYS
    assert SYNC_DAYS == 7
    connected_quietly(web)
    old = strava_job(web, "completed", finished=timezone.now() - timedelta(days=10))
    created_one_more(press_import(web), [old])


@pytest.mark.django_db
def test_a_run_from_an_earlier_connection_needs_no_confirmation(web):
    """As after «Quitar lo sincronizado» and a new connection: the job's rides may be gone."""
    connected_quietly(web, since=timedelta(days=1))
    before = strava_job(web, "completed", finished=timezone.now() - timedelta(days=2))
    created_one_more(press_import(web), [before])


@pytest.mark.django_db
def test_a_fit_run_does_not_count_for_strava(web):
    connected_quietly(web)
    fit_runs = [strava_job(web, "completed", kind="fit", finished=timezone.now() - timedelta(days=2)), strava_job(web, "paused", kind="fit")]
    created_one_more(press_import(web), fit_runs)


@pytest.mark.django_db
def test_without_a_strava_account_nothing_covers(web):
    completed = strava_job(web, "completed", finished=timezone.now() - timedelta(days=2))
    created_one_more(press_import(web), [completed])
    assert StravaAccount.objects.filter(owner=web.owner).exists()


@pytest.mark.django_db
def test_another_owners_runs_neither_block_nor_ask(web):
    connected_quietly(web)
    theirs = [strava_job(web, "paused", owner=web.other), strava_job(web, "completed", owner=web.other, finished=timezone.now() - timedelta(days=2))]
    created_one_more(press_import(web), theirs)


# Edges: the exact end of SYNC_DAYS (a fixed clock), the constant itself, and the date in the viewer's zone.

@pytest.mark.django_db
@pytest.mark.parametrize("later, asks", [(timedelta(0), True), (timedelta(microseconds=1), False)])
def test_the_edge_of_sync_days(web, monkeypatch, later, asks):
    from .services.strava_sync import SYNC_DAYS
    monkeypatch.setattr("django.utils.timezone.now", lambda: SECONDS)
    connected_quietly(web)
    edge = strava_job(web, "completed", finished=SECONDS - timedelta(days=SYNC_DAYS) - later)
    response = press_import(web)
    if asks:
        assert response.status_code == 400 and "Ya importaste" in html(response)
    else:
        created_one_more(response, [edge])


@pytest.mark.django_db
def test_the_warning_follows_sync_days(web, monkeypatch):
    """«Cubierto» is what «Sincronizar ahora» reaches: with 12 days instead of 7, a job finished 10 days ago covers."""
    monkeypatch.setattr("garage.services.strava_sync.SYNC_DAYS", 12)
    connected_quietly(web)
    strava_job(web, "completed", finished=timezone.now() - timedelta(days=10))
    assert press_import(web).status_code == 400


@pytest.mark.django_db
@pytest.mark.parametrize("zone, after, asks", [
    ("Europe/Madrid", "2026-02-01", True),    # the very midnight the job asked from
    ("Europe/Madrid", "2026-02-02", True),
    ("Europe/Madrid", "2026-01-31", False),
    ("America/Argentina/Buenos_Aires", "2026-02-01", True),  # 1 Feb there begins 4 h after 1 Feb in Madrid
    ("America/Argentina/Buenos_Aires", "2026-01-31", False),
    ("Asia/Tokyo", "2026-02-01", False),  # 1 Feb in Tokyo begins 8 h before 1 Feb in Madrid
])
def test_the_date_is_read_in_the_viewers_zone(web, zone, after, asks):
    connected_quietly(web)
    covering = strava_job(web, "completed", finished=timezone.now() - timedelta(days=2))
    web.client.cookies["garage_tz"] = zone
    response = press_import(web, after=after)
    if asks:
        assert response.status_code == 400 and list(ImportRun.objects.all()) == [covering]
    else:
        created_one_more(response, [covering])


@pytest.mark.django_db
@pytest.mark.parametrize("zone, since, done", [
    ("Europe/Madrid", "1 feb 2026", "15 oct 2026, 12:07"),  # a local midnight: the date alone
    ("America/Argentina/Buenos_Aires", "31 ene 2026, 20:00", "15 oct 2026, 7:07"),  # 1 Feb in Madrid began at 20:00 there
])
def test_the_new_texts_give_the_bound_by_the_local_bound_rule(web, monkeypatch, zone, since, done):
    """B14-R2-02 (F21, F22): the job's start in the warning, the «Completado» lead and the Strava page note is the date when it
    is a local midnight in the viewer's zone, else the date and the time; the end is to the minute."""
    monkeypatch.setattr("django.utils.timezone.now", lambda: SECONDS)
    connected_quietly(web)
    web.client.cookies["garage_tz"] = zone
    completed = strava_job(web, "completed", since=FEB_1, finished=SECONDS - timedelta(days=2))

    warning = visible_text(parse(html(press_import(web, after="2026-02-02"))))
    assert f"Ya importaste el histórico desde el {since} (trabajo completado el {done}). Repetirlo no duplica salidas" in warning

    lead = visible_text(parse(html(web.client.get(reverse("garage:history-run", args=[completed.pk])))))
    assert f"Completado: Garage pidió a Strava tus salidas desde el {since} hasta el {done}. Desde entonces" in lead

    strava_job(web, "paused", since=FEB_1)
    assert f"Hay un trabajo sin terminar desde el {since}: continúalo." in visible_text(strava_page(web))
