"""garage-031.4: ride review (bike, gear that counted, preview) and the Salidas list."""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Bike, Category, Item, ItemUsage, MaintenanceRule, ServiceType, UsageMaterializationState, UsageOverride
from .services import usage as usage_service
from .services.home import home_snapshot
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.ownership import InventoryNotFound, InventoryWriteError, create_inventory, retire_inventory
from .services.ride_review import UNCHANGED, review_ride, review_state
from .services.rides import correct_ride, create_manual_ride
from .services.usage import rebuild_usage
from .services.usage_profiles import create_profile_history, set_usage_override

UTC = dt_timezone.utc
T0 = datetime(2026, 1, 1, tzinfo=UTC)


def at(days):
    return T0 + timedelta(days=days)


def build(username):
    owner = get_user_model().objects.create_user(username, password="test-only-password")
    cat = create_inventory(owner, Category, name="Material")
    road = create_inventory(owner, Bike, name="Carretera")
    gravel = create_inventory(owner, Bike, name="Gravel")
    old = create_inventory(owner, Bike, name="Vieja")
    names = ("Cadena", "Casco", "Zapatillas ruta", "Calas", "Zapatillas gravel", "Luz")
    item = {name: create_inventory(owner, Item, name=name, category=cat) for name in names}
    create_installation(owner, item=item["Cadena"], bike=road, parent_item=None, started_at=at(0), ended_at=None, slot="chain")
    create_installation(owner, item=item["Calas"], bike=None, parent_item=item["Zapatillas ruta"], started_at=at(0), ended_at=None, slot=None)
    create_profile_history(owner, name="Siempre", started_at=at(0), items=[item["Casco"]])
    create_profile_history(owner, name="Ruta", bike=road, started_at=at(0), items=[item["Zapatillas ruta"]])
    create_profile_history(owner, name="Gravel", bike=gravel, started_at=at(0), items=[item["Zapatillas gravel"]])
    pending = create_manual_ride(owner, started_at=at(10), name="Vuelta por la sierra", sport_type="cycling",
                                 distance_m=Decimal(92400), moving_time_s=Decimal(13260))
    other = create_manual_ride(owner, started_at=at(5), bike=road, name="Otra", distance_m=Decimal(50000), moving_time_s=Decimal(7200))
    retire_inventory(owner, Bike, old.pk, at=at(2))
    rebuild_usage(owner)
    return SimpleNamespace(owner=owner, road=road, gravel=gravel, old=old, item=item, pending=pending, other=other)


@pytest.fixture
def g(db):
    return build("review-owner")


def counted(g, ride=None):
    ride = ride or g.pending
    return {row.item.name for row in ItemUsage.objects.filter(ride=ride).select_related("item")}


def names(effects):
    return {(effect.label, effect.sign) for effect in effects}


class TestService:
    def test_initial_state(self, g):
        state = review_state(g.owner, g.pending.pk)
        assert state.resolvable and state.current_key == "none" and not state.bike_decided
        assert [bike.name for bike in state.bikes] == ["Carretera", "Gravel"]  # retired before the ride: not offered
        by_name = {c.item.name: c for c in state.candidates}
        assert set(by_name) == {"Casco", "Zapatillas gravel", "Zapatillas ruta"}  # mounted and profile-less items excluded
        assert by_name["Casco"].selected and not by_name["Zapatillas ruta"].selected
        assert by_name["Casco"].usual == {"none", str(g.road.pk), str(g.gravel.pk)}
        assert by_name["Zapatillas ruta"].usual == {str(g.road.pk)}
        assert state.effects == () and not state.changed

    def test_hypothetical_bike_uses_its_usual_gear_and_shows_subtrees(self, g):
        state = review_state(g.owner, g.pending.pk, bike=g.road.pk)
        assert state.selected_gear == {g.item["Casco"].pk, g.item["Zapatillas ruta"].pk}
        assert names(state.effects) == {("Carretera", 1), ("Cadena", 1), ("Zapatillas ruta", 1), ("Calas", 1)}
        assert state.mounted == 1 and state.changed  # only the chain is on the bike; cleats ride on the shoes
        assert not UsageOverride.objects.exists() and counted(g) == {"Casco"}

    def test_save_usual_gear_writes_bike_only(self, g):
        result = review_ride(g.owner, g.pending.pk, bike=g.road.pk, gear=[g.item["Casco"].pk, g.item["Zapatillas ruta"].pk])
        assert result.bike_changed and not result.overrides_changed
        g.pending.refresh_from_db()
        assert g.pending.bike_id == g.road.pk and g.pending.field_provenance["bike"]["kind"] == "manual"
        assert counted(g) == {"Casco", "Cadena", "Zapatillas ruta", "Calas"}
        assert not UsageOverride.objects.exists()

    def test_exceptions_only_for_candidates_and_redundant_ones_are_removed(self, g):
        review_ride(g.owner, g.pending.pk, bike=g.road.pk, gear=[g.item["Casco"].pk, g.item["Zapatillas gravel"].pk])
        assert counted(g) == {"Casco", "Cadena", "Zapatillas gravel"}
        assert {(o.item.name, o.action) for o in UsageOverride.objects.select_related("item")} == {
            ("Zapatillas gravel", "include"), ("Zapatillas ruta", "exclude")}
        state = review_state(g.owner, g.pending.pk)
        assert {c.item.name: c.override for c in state.candidates}["Zapatillas ruta"] == "exclude"
        review_ride(g.owner, g.pending.pk, bike=g.gravel.pk, gear=[g.item["Casco"].pk, g.item["Zapatillas gravel"].pk])
        assert not UsageOverride.objects.exists()
        assert counted(g) == {"Casco", "Zapatillas gravel"}

    def test_invariant_every_candidate_counts_iff_selected(self, g):
        for bike in (g.road.pk, g.gravel.pk, None):
            for gear in ([], [g.item["Casco"].pk], [g.item["Zapatillas ruta"].pk, g.item["Zapatillas gravel"].pk]):
                review_ride(g.owner, g.pending.pk, bike=bike, gear=gear)
                selected = {Item.objects.get(pk=pk).name for pk in gear}
                assert counted(g) & {"Casco", "Zapatillas ruta", "Zapatillas gravel"} == selected

    def test_other_or_unknown_is_saved_for_rides_without_bike(self, g):
        assert home_snapshot(g.owner, at=at(20)).pending_count == 1
        result = review_ride(g.owner, g.pending.pk, bike=None, gear=[g.item["Casco"].pk])
        assert result.bike_changed
        g.pending.refresh_from_db()
        assert "bike" in g.pending.manual_overrides and g.pending.bike_id is None
        assert home_snapshot(g.owner, at=at(20)).pending_count == 0
        assert not review_ride(g.owner, g.pending.pk, bike=None, gear=[g.item["Casco"].pk]).bike_changed

    def test_non_candidate_exceptions_are_preserved_and_reported(self, g):
        set_usage_override(g.owner, ride=g.pending, item=g.item["Cadena"], action="include")
        review_ride(g.owner, g.pending.pk, bike=g.gravel.pk, gear=[g.item["Casco"].pk])
        assert UsageOverride.objects.filter(item=g.item["Cadena"], action="include").exists()
        # The chain is carried by Carretera: an include keeps counting it on a Gravel ride.
        assert [item.name for item in review_state(g.owner, g.pending.pk, bike=g.gravel.pk, gear=[g.item["Casco"].pk]).stale_includes] == ["Cadena"]
        assert review_state(g.owner, g.pending.pk, bike=g.road.pk, gear=[g.item["Casco"].pk]).stale_includes == ()

    def test_candidates_follow_retirement_and_modality(self, g):
        from .services.ownership import reactivate_inventory
        light, shoes = g.item["Luz"], g.item["Zapatillas gravel"]
        create_profile_history(g.owner, name="Sólo MTB", sport_type="mountain_biking", started_at=at(0), items=[light])
        retire_inventory(g.owner, Item, shoes.pk, at=at(8))
        reactivate_inventory(g.owner, Item, shoes.pk, at=at(12))  # retired during the ride (day 10): interval
        names = {c.item.name for c in review_state(g.owner, g.pending.pk).candidates}
        assert names == {"Casco", "Zapatillas ruta"}
        mtb = create_manual_ride(g.owner, started_at=at(15), name="Monte", sport_type="mountain_biking", distance_m=Decimal(1000))
        assert "Luz" in {c.item.name for c in review_state(g.owner, mtb.pk).candidates}
        with pytest.raises(InventoryWriteError):
            review_ride(g.owner, g.pending.pk, bike=UNCHANGED, gear=[shoes.pk])

    def test_retired_bike_cannot_be_chosen(self, g):
        with pytest.raises(InventoryWriteError) as error:
            review_ride(g.owner, g.pending.pk, bike=g.old.pk, gear=[])
        assert error.value.error_dict["bike"][0].code == "retired_reference"

    def test_other_or_unknown_on_a_fit_ride(self, g):
        from .services.rides import import_fit_session
        ride, _ = import_fit_session(g.owner, file_hash="f" * 64, session_index=0, parser_version="synthetic",
                                     observations={"started_at": at(11), "sport_type": "cycling", "distance_m": Decimal(30000)})
        assert review_state(g.owner, ride.pk).source == "Archivo FIT"
        assert ride.pk in {r.pk for r in __import__("garage.services.home", fromlist=["x"]).pending_rides(g.owner)}
        assert review_ride(g.owner, ride.pk, bike=None, gear=[g.item["Casco"].pk]).bike_changed
        ride.refresh_from_db()
        assert ride.manual_overrides.get("bike", "missing") is None and ride.field_provenance["bike"]["kind"] == "manual"
        assert ride.field_provenance["distance_m"]["kind"] == "fit"

    def test_validation(self, g):
        foreign = build("review-foreign")
        for kwargs in ({"gear": [g.item["Luz"].pk]}, {"gear": [g.item["Cadena"].pk]}, {"gear": [foreign.item["Casco"].pk]},
                       {"gear": ["not-a-uuid"]}, {"bike": foreign.road.pk, "gear": []}):
            with pytest.raises(InventoryWriteError):
                review_ride(g.owner, g.pending.pk, **{"bike": UNCHANGED, **kwargs})
        with pytest.raises(InventoryNotFound):
            review_ride(g.owner, foreign.pending.pk, bike=UNCHANGED, gear=[])
        with pytest.raises(InventoryWriteError):
            review_state(g.owner, g.pending.pk, bike=g.road.pk, gear=[g.item["Luz"].pk])
        assert counted(g) == {"Casco"} and not UsageOverride.objects.exists()

    def test_ride_without_start(self, g):
        from .services.rides import import_fit_session, withdraw_source
        ride, source = import_fit_session(g.owner, file_hash="d" * 64, session_index=0, parser_version="synthetic",
                                          observations={"started_at": at(12), "sport_type": "cycling"})
        withdraw_source(g.owner, source.pk)
        assert not review_state(g.owner, ride.pk).resolvable
        with pytest.raises(InventoryWriteError) as error:
            review_ride(g.owner, ride.pk, bike=g.road.pk, gear=[])
        assert error.value.error_dict["ride"][0].code == "start_required"

    def test_equivalent_to_public_services(self, db):
        a, b = build("eq-a"), build("eq-b")
        review_ride(a.owner, a.pending.pk, bike=a.road.pk, gear=[a.item["Casco"].pk, a.item["Zapatillas gravel"].pk])
        correct_ride(b.owner, b.pending.pk, bike=b.road)
        set_usage_override(b.owner, ride=b.pending, item=b.item["Zapatillas gravel"], action="include")
        set_usage_override(b.owner, ride=b.pending, item=b.item["Zapatillas ruta"], action="exclude")

        def rows(owner):
            return sorted((u.item.name, u.ride.name, u.started_at, u.bike.name if u.bike else None, u.distance_m, u.moving_time_s,
                           u.timer_time_s, u.ride_count) for u in ItemUsage.objects.filter(owner=owner).select_related("item", "ride", "bike"))
        assert rows(a.owner) == rows(b.owner)
        assert {(o.item.name, o.action) for o in UsageOverride.objects.filter(owner=a.owner).select_related("item")} == \
            {(o.item.name, o.action) for o in UsageOverride.objects.filter(owner=b.owner).select_related("item")}

    def test_equivalent_when_not_initialized_including_provenance(self, db):
        a, b = build("eqn-a"), build("eqn-b")
        for owner in (a.owner, b.owner):
            UsageMaterializationState.objects.filter(owner=owner).update(initialized_at=None)
        review_ride(a.owner, a.pending.pk, bike=a.gravel.pk, gear=[a.item["Zapatillas ruta"].pk])
        correct_ride(b.owner, b.pending.pk, bike=b.gravel)
        set_usage_override(b.owner, ride=b.pending, item=b.item["Zapatillas ruta"], action="include")
        set_usage_override(b.owner, ride=b.pending, item=b.item["Casco"], action="exclude")
        set_usage_override(b.owner, ride=b.pending, item=b.item["Zapatillas gravel"], action="exclude")

        def rows(owner):
            return sorted((u.item.name, u.ride.name, u.bike.name if u.bike else None, u.distance_m)
                          for u in ItemUsage.objects.filter(owner=owner).select_related("item", "ride", "bike"))
        assert rows(a.owner) == rows(b.owner)
        for x, y in ((a, b),):
            x.pending.refresh_from_db(); y.pending.refresh_from_db()
            assert x.pending.manual_overrides.keys() == y.pending.manual_overrides.keys()
            assert {k: v["kind"] for k, v in x.pending.field_provenance.items()} == {k: v["kind"] for k, v in y.pending.field_provenance.items()}
        assert UsageMaterializationState.objects.get(owner=a.owner).initialized_at is not None

    def test_single_ride_rebuild_when_initialized(self, g):
        with patch.object(usage_service, "_rebuild_all_locked", wraps=usage_service._rebuild_all_locked) as full, \
                patch.object(usage_service, "_rebuild_ride_locked", wraps=usage_service._rebuild_ride_locked) as one:
            review_ride(g.owner, g.pending.pk, bike=g.road.pk, gear=[g.item["Casco"].pk, g.item["Zapatillas gravel"].pk])
        assert full.call_count == 0 and one.call_count == 1

    def test_full_rebuild_when_not_initialized(self, g):
        UsageMaterializationState.objects.filter(owner=g.owner).update(initialized_at=None)
        with patch.object(usage_service, "_rebuild_all_locked", wraps=usage_service._rebuild_all_locked) as full:
            review_ride(g.owner, g.pending.pk, bike=UNCHANGED, gear=[g.item["Zapatillas gravel"].pk])
        assert full.call_count == 1
        assert UsageMaterializationState.objects.get(owner=g.owner).initialized_at is not None


def write_queries(queries):
    return [q for q in queries if q["sql"].lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}]


class TestViews:
    def url(self, g, name="ride-review"):
        return reverse("garage:" + name, args=[g.pending.pk])

    def test_page(self, g, client):
        client.force_login(g.owner)
        with CaptureQueriesContext(connection) as queries:
            response = client.get(self.url(g) + "?next=/garage/")
        html = response.content.decode()
        assert response.status_code == 200 and not write_queries(queries)
        for text in ("Vuelta por la sierra", "92,4", "3 h 41", "25,1", "¿Con qué bici?", "Esta salida no tiene bici",
                     'name="bike"', "Otra o desconocida", "Material que llevaste", 'data-usual="', "Habitual",
                     "Sin cambios en los contadores.", 'data-preview="', "Excepciones avanzadas", 'name="next" value="/garage/"'):
            assert text in html, text
        assert "Cadena" not in html.split("Material que llevaste")[1].split("Al guardar")[0]

    def test_tags_for_an_undecided_ride(self, g, client):
        client.force_login(g.owner)
        html = client.get(self.url(g)).content.decode()
        assert 'data-selected="none"' in html and 'name="shown_bike" value="none"' in html
        casco = html.split(f'data-tag="{g.item["Casco"].pk}"')[1].split("</span>")[0]
        assert casco.endswith(">Habitual") and "Añadido" not in casco
        ruta = html.split(f'data-tag="{g.item["Zapatillas ruta"].pk}"')[1].split("</span>")[0]
        assert ruta == ">"  # neither usual nor selected without a bike: no tag
        assert f'data-usual="{g.road.pk}"' in html

    def test_no_js_round_trip(self, g, client):
        client.force_login(g.owner)
        page = client.post(self.url(g), {"bike": "none", "gear": [str(g.item["Casco"].pk)], "action": "preview", "shown_bike": "none"})
        html = page.content.decode()
        assert page.status_code == 200 and 'value="none" data-name="" checked' in html
        saved = client.post(self.url(g), {"bike": "none", "gear": [str(g.item["Casco"].pk)], "action": "save", "shown_bike": "none"})
        assert saved.status_code == 302
        g.pending.refresh_from_db()
        assert "bike" in g.pending.manual_overrides

    def test_no_js_bike_switch_shows_usual_gear_before_saving(self, g, client):
        client.force_login(g.owner)
        response = client.post(self.url(g), {"bike": str(g.road.pk), "gear": [str(g.item["Casco"].pk)], "action": "save", "shown_bike": "none"})
        html = response.content.decode()
        assert response.status_code == 200 and "Material habitual de la nueva bici marcado" in html
        assert f'id="gear-{g.item["Zapatillas ruta"].pk}" data-usual="{g.road.pk}" checked' in html
        g.pending.refresh_from_db()
        assert "bike" not in g.pending.manual_overrides and not UsageOverride.objects.exists()

    def test_preview_fragment_has_no_writes(self, g, client):
        client.force_login(g.owner)
        params = {"bike": str(g.road.pk), "gear": [str(g.item["Casco"].pk), str(g.item["Zapatillas ruta"].pk)]}
        with CaptureQueriesContext(connection) as queries:
            response = client.get(self.url(g, "ride-review-preview"), params)
        html = response.content.decode()
        assert response.status_code == 200 and not write_queries(queries)
        assert "+92,4 km" in html and "Calas" in html and "Carretera" in html and "<html" not in html
        bad = client.get(self.url(g, "ride-review-preview"), {"bike": str(g.road.pk), "gear": [str(g.item["Luz"].pk)]})
        assert bad.status_code == 400 and 'role="alert"' in bad.content.decode()

    def test_post_preview_without_javascript_writes_nothing(self, g, client):
        client.force_login(g.owner)
        data = {"bike": str(g.road.pk), "gear": [str(g.item["Casco"].pk)], "action": "preview", "next": "/garage/"}
        with CaptureQueriesContext(connection) as queries:
            response = client.post(self.url(g), data)
        assert response.status_code == 200 and "+92,4 km" in response.content.decode()
        assert not write_queries(queries)

    def test_save_redirects_to_safe_next_with_status_messages(self, g, client):
        kind = save_maintenance(g.owner, ServiceType, name="Revisar calas")
        save_maintenance(g.owner, MaintenanceRule, item=g.item["Calas"], service_type=kind, ride_count=1, anchor_at=at(8))
        client.force_login(g.owner)
        response = client.post(self.url(g), {"bike": str(g.road.pk), "gear": [str(g.item["Casco"].pk), str(g.item["Zapatillas ruta"].pk)],
                                             "action": "save", "next": "https://evil.example/"})
        assert response.status_code == 302 and response.url == "/garage/"
        texts = [str(message) for message in get_messages(response.wsgi_request)]
        assert "Salida revisada." in texts and "Revisar calas · Calas: En curso → Vencido" in texts
        assert counted(g) == {"Casco", "Cadena", "Zapatillas ruta", "Calas"}

    def test_invalid_save_shows_errors(self, g, client):
        client.force_login(g.owner)
        response = client.post(self.url(g), {"bike": str(g.road.pk), "gear": [str(g.item["Luz"].pk)], "action": "save"})
        html = response.content.decode()
        assert response.status_code == 400 and "Elige material de la lista." in html
        assert f'value="{g.road.pk}" data-name="Carretera" checked' not in html  # invalid gear: falls back to the saved state
        assert counted(g) == {"Casco"}

    def test_access(self, g, client):
        assert client.get(self.url(g)).status_code == 302
        stranger = build("review-stranger")
        client.force_login(stranger.owner)
        assert client.get(self.url(g)).status_code == 404
        assert client.get(self.url(g, "ride-review-preview")).status_code == 404
        assert client.post(self.url(g), {"action": "save", "gear": []}).status_code == 404

    def test_back_link_and_pending_filter(self, g, client):
        client.force_login(g.owner)
        rides = reverse("garage:usage-ride-list")
        html = client.get(self.url(g) + f"?next={rides}").content.decode()
        assert 'aria-label="Volver a Salidas"' in html
        assert 'aria-label="Volver a Garaje"' in client.get(self.url(g) + "?next=/garage/").content.decode()
        listed = client.get(rides + "?pending=1")
        assert [row["ride"].pk for row in listed.context["rows"]] == [g.pending.pk]
        assert "Ver todas" in listed.content.decode()

    def test_rides_list_links_to_review_with_one_resolver_snapshot(self, g, client):
        for number in range(15):
            create_manual_ride(g.owner, started_at=at(30 + number), bike=g.road, name=f"Extra {number}", distance_m=Decimal(1000))
        client.force_login(g.owner)
        with CaptureQueriesContext(connection) as queries:
            response = client.get(reverse("garage:usage-ride-list"))
        html = response.content.decode()
        assert response.status_code == 200 and len(queries) <= 25, len(queries)
        assert reverse("garage:ride-review", args=[g.pending.pk]) in html and "Sin bici" in html and "Casco" in html
