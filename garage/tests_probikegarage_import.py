"""garage-043: importing a ProBikeGarage dump into an empty Garage, and verifying it.

Every dump here is synthetic, built in this file: the owner's real dump is never
read by the suite, copied to fixtures or quoted.
"""
import copy
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
import json
import logging
from pathlib import Path
import stat

import pytest
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext

from .importers.probikegarage import (BASELINE_SOURCE, FALLBACK_CATEGORY, SINCE_ALWAYS_NOTE, TYPE_CATEGORIES, build_plan, category_for,
                                      loads_dump)
from .models import (ActivitySource, Bike, Category, Installation, Item, MaintenanceRule, Ride, ServiceEvent, ServiceType, StravaAccount,
                     StravaGear, UsageBaseline)
from .services.categories import STARTER, _canonical
from .services.lifespan import LIFE_TYPE, inherit_lifespan, is_life, lifespan_rule
from .services.maintenance import save_maintenance
from .services.maintenance_due import maintenance_due
from .services.ownership import InventoryWriteError, _lock_owner, create_inventory
from .services.probikegarage_import import ImportFailed, ImportRejected, apply, preview, read_mapping, verify
from .services.rides import create_manual_ride
from .services.strava_sources import rebuild_rides_locked, store_activity
from .services.strava_sync import ENV_SCOPES
from .services.usage import rebuild_usage, summarize_item_usage

UTC = dt_timezone.utc
WRITES = {"INSERT", "UPDATE", "DELETE"}
ATHLETE = 4343
OWNED = (Category, Bike, Item, Installation, ServiceType, MaintenanceRule, ServiceEvent, UsageBaseline, StravaGear)


def when(month, day, hour=10, minute=0):
    return datetime(2026, month, day, hour, minute, tzinfo=UTC)


def iso(instant):
    return instant.strftime("%Y-%m-%dT%H:%M:%SZ")


NULL = "0001-01-01T00:00:00Z"
EXPORTED = when(3, 25, 12)
BIKE = "b1b1b1b1-0000-4000-8000-000000000001"
C = {name: f"c{index:07d}-0000-4000-8000-000000000000" for index, name in enumerate(
    ("chain", "fork", "pedals", "cleats", "pads_old", "pads_new", "hub", "bearings", "roldana", "misc"), start=1)}


def interval(iid, title, kind, value, repeat, nxt=None, notes=""):
    return {"id": iid, "title": title, "type": kind, "value": value, "repeat": repeat, "next": nxt, "notes": notes, "snooze": None}


def usage(distance=0, moving=0, elevation=0, rides=0):
    return {"distance": distance, "moving_time": moving, "elevation_gain": elevation, "rides": rides, "energy": None}


def component(key, name, kind, *, retired=NULL, notes="", initial=None, used=None, intervals=()):
    return {"id": C[key], "name": name, "type": kind, "notes": notes, "retired_at": retired,
            "initial_usage": {"rides": 0, "distance": 0, "moving_time": 0, "elevation_gain": 0, **(initial or {})},
            "usage": used or usage(), "service_intervals": list(intervals), "current_installations": []}


def mount(iid, key, *, bike=BIKE, parent=None, added, removed=NULL):
    return {"id": iid, "component_id": C[key], "target_type": "component" if parent else "bike", "target_id": C[parent] if parent else bike,
            "bike_id": "" if parent else bike, "added_at": added if isinstance(added, str) else iso(added),
            "removed_at": removed if isinstance(removed, str) else iso(removed), "ride_tags": [], "included_ride_tags": [], "excluded_ride_tags": []}


def service(sid, title, served, *, target, parts, intervals=(), extra_parts=(), extra_intervals=(), notes=None, target_type=None):
    row = {"id": sid, "title": title, "serviced_at": iso(served), "target_type": target_type or ("service_interval" if intervals else "component"),
           "target_id": target, "bikes_ids": [BIKE], "components_ids": [C[p] for p in parts], "service_intervals_ids": list(intervals),
           "stats": {"distance": 0, "moving_time": 0, "elapsed_time": 0, "elevation_gain": 0, "rides": 0}}
    if notes is not None:
        row["notes"] = notes
    if extra_parts:
        row["target_components_ids"] = [C[p] for p in extra_parts]
    if extra_intervals:
        row["target_service_intervals_ids"] = list(extra_intervals)
    return row


# Rides: (strava id, start, metres, seconds, elevation, with the bike)
RIDES = ((7001, when(1, 3, 9), 30000, 3600, 300, True), (7002, when(1, 12), 40000, 5400, 500, True),
         (7003, when(2, 10), 50000, 7200, 800, True), (7004, when(3, 15), 20000, 3000, 200, True),
         (7005, when(3, 20), 10000, 1800, 100, False))


def synthetic_dump():
    """One bike; active, retired and nested parts; «since always»; initial usage; every interval type."""
    chain = [interval("i-lube", "Lubricar", "distance", 300000, True, 280000, notes="Cera"),
             interval("i-life1", "Max life", "distance", 3000000, False, 2890000),
             interval("i-life2", "Max Life", "moving-time", 360000, False, 344400),
             interval("i-life3", "Max life", "distance", 5000000, False, 4890000)]
    fork = [interval("i-fork-days", "Revisión", "elapsed-time", 5184000, True, -1825200),
            interval("i-fork-oil", "Aceite", "moving-time", 180000, True, 177000)]
    pedals = [interval("i-full", "Full service", "moving-time", 360000, True, 357000),
              interval("i-tight", "Check tightness", "distance", 500000, True, 480000),
              interval("i-clip", "Check & lube", "elapsed-time", 31536000, True, 28677600)]
    bearings = [interval("i-bear-rides", "Revisar", "rides", 10, True, 7), interval("i-bear-elev", "Engrasar", "elevation-gain", 20000, True, 18500)]
    three = usage(110000, 15600, 1500, 3)
    return {
        "format": "probikegarage-dump", "version": 2, "exported_at": "2026-03-25T12:00:00.000Z", "user_id": "u-synthetic",
        "bikes": [{"id": BIKE, "name": "Bici sintética", "default": False, "retired_at": NULL,
                   "strava_bike": {"id": "b900001", "name": "Strava sintética", "nickname": "", "brand_name": "Marca", "model_name": "Modelo",
                                   "description": "", "frame_type": 1},
                   "usage": usage(140000, 19200, 1800, 4)}],
        "components": [
            component("chain", "Cadena sintética", "chain", notes="Precio 30 €", used=three, intervals=chain),
            component("fork", "Horquilla sintética", "fork", used=usage(140000, 19200, 1800, 4), intervals=fork),
            component("pedals", "Pedales sintéticos", "pedals", used=three, intervals=pedals),
            component("cleats", "Calas sintéticas", "other", used=three),
            component("pads_old", "Pastillas", "brake-pads", retired=iso(when(2, 1)),
                      initial={"distance": 1300000, "moving_time": 298800, "elevation_gain": 1000}, used=usage(1340000, 304200, 1500, 1)),
            component("pads_new", "Pastillas", "brake-pads", used=usage(70000, 10200, 1000, 2)),
            component("hub", "Buje trasero", "hub", used=three),
            component("bearings", "Rodamientos traseros", "bearings", used=three, intervals=bearings),
            component("roldana", "Roldanas cerámicas", "other", initial={"distance": 50000}, used=usage(50000),
                      intervals=[interval("i-rold", "Limpiar", "distance", 1000000, True, 1000000)]),
            component("misc", "Cosa rara", "gizmo", retired=iso(when(3, 1)), used=usage(90000, 12600, 1300, 2)),
        ],
        "installations": [
            mount("m-chain", "chain", added=when(1, 10)),
            mount("m-fork", "fork", added=NULL),
            mount("m-pedals", "pedals", added=when(1, 5)),
            mount("m-cleats", "cleats", parent="pedals", added=when(1, 6)),
            mount("m-pads-old", "pads_old", added=when(1, 5), removed=when(2, 1)),
            mount("m-pads-new", "pads_new", added=when(2, 1)),
            mount("m-hub", "hub", added=when(1, 5)),
            mount("m-bearings", "bearings", parent="hub", added=when(1, 5)),
            mount("m-misc", "misc", added=when(1, 5)),
        ],
        "services": [
            service("s-lube", "Lubricar", when(2, 15), target="i-lube", parts=["chain"], intervals=["i-lube"], notes="Con cera"),
            service("s-kit", "Refresh kit", when(2, 20), target=C["pedals"], target_type="component", parts=["pedals", "cleats"],
                    intervals=["i-full", "i-tight", "i-clip"], extra_parts=["cleats"], extra_intervals=["i-clip", "i-tight", "i-full"],
                    notes="Kit completo"),
            service("s-oil", "Servicio", when(3, 1), target="i-fork-oil", parts=["fork"], intervals=["i-fork-oil"]),
            service("s-measure", "Medición ", when(3, 10), target=C["pads_new"], parts=["pads_new"], notes="1,2 mm"),
            service("s-swap", "Cambio de cadena", when(1, 10), target="i-life1", parts=["chain"], intervals=["i-life1"]),
            service("s-old-oil", "Aceite", when(1, 20), target=C["fork"], parts=["fork"]),
        ],
        "rides": [{"strava_id": sid, "started_at": iso(start), "distance": distance, "moving_time": moving, "elapsed_time": moving + 60,
                   "elevation_gain": elevation, "bike": BIKE[:8] if bike else "", "gear_id": "b900001" if bike else "",
                   "sport_type": "Ride", "tags": "ride", "avg_power": 0.0, "work_output": 0, "components": []}
                  for sid, start, distance, moving, elevation, bike in RIDES],
    }


def clean_dump():
    """The synthetic dump without the three differences it shows on purpose (see the verification tests)."""
    dump = synthetic_dump()
    parts = {row["id"]: row for row in dump["components"]}
    parts[C["chain"]]["service_intervals"] = [row for row in parts[C["chain"]]["service_intervals"] if row["id"] != "i-life3"]
    parts[C["pads_old"]]["initial_usage"]["elevation_gain"] = 0
    parts[C["pads_old"]]["usage"]["elevation_gain"] = 500
    parts[C["roldana"]]["service_intervals"] = []
    return dump


def write_dump(tmp_path, dump, name="dump.json"):
    path = tmp_path / name
    path.write_text(json.dumps(dump), encoding="utf-8")
    return path


def writes(queries):
    return [q["sql"] for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES]


def owned_rows(owner):
    return {model.__name__: model.objects.filter(owner=owner).count() for model in OWNED}


@pytest.fixture
def owner(db, django_user_model):
    return django_user_model.objects.create_user("pbg-owner", password="synthetic-only")


@pytest.fixture
def other(db, django_user_model):
    return django_user_model.objects.create_user("pbg-other", password="synthetic-only")


@pytest.fixture
def imported(owner):
    result = apply(owner, synthetic_dump(), zone=UTC)
    return result


def item(owner, key, result):
    return Item.objects.get(owner=owner, pk=result.mapping["components"][C[key]])


# The pure plan ------------------------------------------------------------------

class TestCategories:
    @pytest.mark.parametrize("name,expected", [
        ("Calas Shimano SPD", "Calas"), ("Cálas", "Calas"), ("Roldanas cerámicas", "Roldanas"), ("Roldana", "Roldanas"),
        ("NUBE trasera", "Insertos tubeless"), ("Inserto Vittoria", "Insertos tubeless"), ("Escalas", "Otros"), ("Cosa", "Otros"),
    ])
    def test_other_by_name(self, name, expected):
        category, icon, known = category_for("other", name)
        assert (category, known) == (expected, True) and icon

    def test_unknown_type_goes_to_otros_and_warns(self):
        assert category_for("gizmo", "Lo que sea") == (*FALLBACK_CATEGORY, False)
        plan = build_plan(synthetic_dump())
        assert any("«Cosa rara»: tipo 'gizmo' sin categoría propia: va a «Otros»" in str(w) for w in plan.warnings)

    def test_starter_names_keep_their_icons(self):
        starter = {_canonical(name): icon for _, name, icon in STARTER}
        shared = [(name, icon) for name, icon in TYPE_CATEGORIES.values() if _canonical(name) in starter]
        assert len(shared) >= 25 and all(starter[_canonical(name)] == icon for name, icon in shared)
        assert {"Frenos", "Rodamientos", "Insertos tubeless"} <= {name for name, _ in TYPE_CATEGORIES.values()}
        assert TYPE_CATEGORIES["fork"] == ("Horquilla de suspensión", "suspension_fork")


class TestPlan:
    def test_counts_and_order(self):
        plan = build_plan(synthetic_dump())
        assert plan.ok, plan.errors
        assert (len(plan.bikes), len(plan.items), len(plan.installations)) == (1, 10, 9)
        assert [m.depth for m in plan.installations] == sorted(m.depth for m in plan.installations)  # bikes, then nested parts
        assert {m.pbg_id for m in plan.installations if m.depth} == {"m-cleats", "m-bearings"}
        assert [name for name, _ in plan.categories] == ["Cadena", "Horquilla de suspensión", "Pedales", "Calas", "Pastillas", "Buje",
                                                         "Rodamientos", "Roldanas", "Otros"]
        assert sum(not r.life for r in plan.rules) == 9 and sum(r.life for r in plan.rules) == 1
        # Refresh kit: three interventions on the pedals (one per interval) and one on the cleats.
        kit = [(e.component_id, e.service_type, e.notes) for e in plan.events if e.service_id == "s-kit"]
        assert kit == [(C["pedals"], "Full service", "Refresh kit. Kit completo"), (C["pedals"], "Check tightness", "Refresh kit. Kit completo"),
                       (C["pedals"], "Check & lube", "Refresh kit. Kit completo"), (C["cleats"], "Refresh kit", "Kit completo")]
        assert len(plan.events) == 9 and len(plan.baselines) == 3 and len(plan.rides) == 5

    def test_since_always_is_the_earliest_of_its_bike(self):
        plan = build_plan(synthetic_dump())
        fork = next(m for m in plan.installations if m.pbg_id == "m-fork")
        assert (fork.started_at, fork.ended_at, fork.notes, fork.since_always) == (when(1, 3, 9), None, SINCE_ALWAYS_NOTE, True)  # first ride
        dump = synthetic_dump()
        dump["rides"] = []
        fork = next(m for m in build_plan(dump).installations if m.pbg_id == "m-fork")
        assert fork.started_at == when(1, 5)  # the earliest other mount of the bike

    def test_intervals(self):
        plan = build_plan(synthetic_dump())
        rules = {r.interval_ids: r for r in plan.rules}
        assert rules[("i-fork-days",)].thresholds == (("calendar_days", 60),)
        assert rules[("i-bear-rides",)].thresholds == (("ride_count", 10),)
        assert rules[("i-bear-elev",)].thresholds == (("elevation_gain_m", Decimal("20000.000")),)
        assert rules[("i-lube",)].notes == "Cera" and rules[("i-lube",)].anchor_at == when(1, 10)
        assert rules[("i-rold",)].anchor_at is None  # never mounted: «Sin datos» until its first intervention
        life = rules[("i-life1", "i-life2", "i-life3")]
        assert life.life and life.service_type == LIFE_TYPE
        assert dict(life.thresholds) == {"distance_m": Decimal("3000000.000"), "moving_time_s": Decimal("360000.000")}
        assert any("i-life3" in str(w) and "se conserva el primero" in str(w) for w in plan.warnings)

    @pytest.mark.parametrize("seconds,days", [(5184000, 60), (31536000, 365), (15724800, 182), (100, 1), (129600, 2)])
    def test_elapsed_time_in_whole_days(self, seconds, days):
        dump = synthetic_dump()
        dump["components"][1]["service_intervals"][0]["value"] = seconds
        rule = next(r for r in build_plan(dump).rules if r.interval_ids == ("i-fork-days",))
        assert rule.thresholds == (("calendar_days", days),)

    def test_baselines_and_warnings(self):
        plan = build_plan(synthetic_dump())
        assert [(b.component_id, b.metric, b.cut_at, b.value) for b in plan.baselines] == [
            (C["pads_old"], "distance_m", when(1, 5), Decimal("1300000.000")),
            (C["pads_old"], "moving_time_s", when(1, 5), Decimal("298800.000")),
            (C["roldana"], "distance_m", EXPORTED, Decimal("50000.000"))]
        text = "\n".join(str(w) for w in plan.warnings)
        assert "«Pastillas»: el desnivel inicial (1000 m) no se guarda" in text
        assert "«Roldanas cerámicas»: uso inicial de una pieza nunca montada" in text
        assert "«Cosa rara»: sigue abierto: se cerrará al retirar su componente" in text
        assert ("services s-old-oil «Aceite»: no marcaba ningún intervalo en «Horquilla sintética»: en Garage reinicia su regla «Aceite» "
                "(mismo tipo, regla general de las intervenciones)") in text

    def test_decimal_json(self):
        dump = loads_dump('{"value": 1.5, "other": 2}')
        assert dump == {"value": Decimal("1.5"), "other": 2}
        with pytest.raises(Exception):
            loads_dump('{"value": NaN}')


def broken(change):
    dump = synthetic_dump()
    change(dump)
    return dump


def part(dump, key):
    return next(row for row in dump["components"] if row["id"] == C[key])


def inst(dump, iid):
    return next(row for row in dump["installations"] if row["id"] == iid)


class TestValidation:
    @pytest.mark.parametrize("change,message", [
        (lambda d: d.update(version=3), "volcado: versión 3 no admitida: se esperaba 2"),
        (lambda d: d.update(format="otro"), "volcado: formato 'otro' desconocido"),
        (lambda d: inst(d, "m-chain").update(component_id="nope"), "installations m-chain: referencia rota: «component_id» 'nope'"),
        (lambda d: inst(d, "m-cleats").update(target_id="nope"), "installations m-cleats «Calas sintéticas»: referencia rota: «target_id» 'nope'"),
        (lambda d: d["installations"].append(mount("m-chain-2", "chain", added=when(2, 1))),
         "installations m-chain-2 «Cadena sintética»: se solapa con el montaje m-chain del mismo componente"),
        (lambda d: inst(d, "m-pads-new").update(removed_at=inst(d, "m-pads-new")["added_at"]),
         "installations m-pads-new «Pastillas»: el montaje termina antes de empezar"),
        (lambda d: inst(d, "m-chain").update(added_at="2026-01-10T10:00:00"),
         "installations m-chain «Cadena sintética»: «added_at» es un instante sin zona horaria"),
        (lambda d: part(d, "chain")["service_intervals"][0].update(value=0), "service_intervals i-lube «Lubricar»: «value» 0 debe ser un número mayor que 0"),
        (lambda d: part(d, "chain")["service_intervals"][0].update(type="weird"), "service_intervals i-lube «Lubricar»: tipo de intervalo 'weird' desconocido"),
        (lambda d: part(d, "chain")["service_intervals"].append(interval("i-lube-2", "lubricar ", "distance", 1, True)),
         "service_intervals i-lube-2 «lubricar»: otro intervalo repetible de este componente (i-lube) tiene el mismo título"),
        (lambda d: part(d, "pads_old").update(retired_at=iso(when(1, 20))),
         "installations m-pads-old «Pastillas»: el montaje sigue después de la retirada de su componente"),
        (lambda d: d["services"][0].update(components_ids=[C["chain"], "nope"]), "services s-lube «Lubricar»: referencia rota: «components_ids»"),
        (lambda d: d["services"][0].update(service_intervals_ids=["i-full"]),
         "services s-lube «Lubricar»: el intervalo i-full es de un componente que no está en la intervención"),
        (lambda d: d["installations"].append(mount("m-loop", "pedals", parent="cleats", added=when(3, 20))), "los montajes anidados forman un ciclo"),
        (lambda d: d["services"].append(dict(d["services"][0])), "services s-lube: «id» repetido"),
        # Values that are not text never raise: they are broken references or unknown types.
        (lambda d: inst(d, "m-chain").update(target_id=["x"]), "installations m-chain «Cadena sintética»: referencia rota: «target_id»"),
        (lambda d: d["services"][0].update(target_id={"x": 1}), "services s-lube «Lubricar»: referencia rota: «target_id»"),
        (lambda d: part(d, "chain")["service_intervals"][0].update(type=["x"]), "service_intervals i-lube «Lubricar»: tipo de intervalo ['x'] desconocido"),
        (lambda d: part(d, "chain").update(name=""), f"components {C['chain']}: «name» está vacío"),
        (lambda d: d["services"][0].update(serviced_at=NULL), "services s-lube «Lubricar»: «serviced_at» tiene la fecha nula de ProBikeGarage"),
        (lambda d: d["rides"].append(dict(d["rides"][0], strava_id=7999, bike="zzzzzzzz")), "rides 7999: «bike» 'zzzzzzzz' no identifica una única bici"),
    ])
    def test_rejected_before_writing(self, owner, change, message):
        dump = broken(change)
        plan = build_plan(dump)
        assert not plan.ok and any(message in str(error) for error in plan.errors), [str(e) for e in plan.errors]
        with CaptureQueriesContext(connection) as queries, pytest.raises(ImportRejected) as rejected:
            apply(owner, dump, zone=UTC)
        assert not writes(queries) and any(message in error for error in rejected.value.report.errors)
        assert set(owned_rows(owner).values()) == {0}

    def test_since_always_needs_a_reference(self):
        dump = synthetic_dump()
        dump["bikes"].append(dict(dump["bikes"][0], id="b2b2b2b2-0000-4000-8000-000000000002", name="Otra",
                                  strava_bike={"id": "b900002", "name": "", "brand_name": "", "model_name": ""}))
        dump["installations"].append(mount("m-alone", "roldana", bike="b2b2b2b2-0000-4000-8000-000000000002", added=NULL))
        errors = [str(e) for e in build_plan(dump).errors]
        assert errors == ["installations m-alone «Roldanas cerámicas»: montado «desde siempre» (fecha nula) sin ningún otro montaje "
                          "ni salida de la bici de la que tomar la fecha"]

    def test_not_an_empty_garage(self, owner, other):
        create_inventory(other, Bike, name="Ajena")  # another owner's Garage does not count
        assert preview(owner, synthetic_dump()).report.errors == ()
        create_inventory(owner, Bike, name="Ya está")
        report = preview(owner, synthetic_dump()).report
        assert report.errors[0].startswith("Garage: el propietario ya tiene 1 bicis y 0 objetos")
        with pytest.raises(ImportRejected):
            apply(owner, synthetic_dump(), zone=UTC)
        assert Item.objects.filter(owner=owner).count() == 0


# Dry run, query budget and the command -------------------------------------------

def scaled_dump(copies):
    """`copies` chains in sequence on one bike, each with a rule, an intervention and a reading."""
    dump = synthetic_dump()
    dump["components"], dump["installations"], dump["services"] = [], [], []
    for index in range(copies):
        cid = f"d{index:07d}-0000-4000-8000-000000000000"
        dump["components"].append({"id": cid, "name": f"Cadena {index}", "type": "chain", "notes": "", "retired_at": NULL,
                                   "initial_usage": {"distance": 1000, "moving_time": 0, "rides": 0, "elevation_gain": 0}, "usage": usage(),
                                   "service_intervals": [interval(f"iv-{index}", "Lubricar", "distance", 300000, True)]})
        dump["installations"].append({"id": f"mi-{index}", "component_id": cid, "target_type": "bike", "target_id": BIKE, "bike_id": BIKE,
                                      "added_at": iso(when(1, 1) + timedelta(days=index)),
                                      "removed_at": iso(when(1, 1) + timedelta(days=index + 1))})
        dump["services"].append({"id": f"sv-{index}", "title": "Lubricar", "serviced_at": iso(when(1, 1, 12) + timedelta(days=index)),
                                 "target_type": "service_interval", "target_id": f"iv-{index}", "bikes_ids": [BIKE],
                                 "components_ids": [cid], "service_intervals_ids": [f"iv-{index}"]})
    return dump


class TestDryRun:
    def test_preview_writes_nothing_and_reads_a_constant_number_of_queries(self, owner):
        with CaptureQueriesContext(connection) as small:
            report = preview(owner, scaled_dump(3)).report
        with CaptureQueriesContext(connection) as large:
            preview(owner, scaled_dump(40))
        assert not writes(small) and not writes(large)
        assert len(small) == len(large) <= 6
        assert report.totals["items"] == 3 and not report.errors

    def test_command_dry_run(self, owner, tmp_path, capsys):
        path = write_dump(tmp_path, synthetic_dump())
        with CaptureQueriesContext(connection) as queries:
            call_command("garage_import_probikegarage", str(path), "--owner", str(owner.pk), "--dry-run", "--mapping", str(tmp_path / "m.json"))
        out = capsys.readouterr().out
        assert not writes(queries) and set(owned_rows(owner).values()) == {0} and not (tmp_path / "m.json").exists()
        assert "Previsualización: no se ha escrito nada." in out and "(--dry-run: no se guarda el mapa)" in out
        assert "Categorías: 9 nuevas · 0 reutilizadas" in out and "Intervenciones: 9" in out and "Salidas del volcado: 5" in out
        assert "Categorías nuevas: Cadena, Horquilla de suspensión, Pedales, Calas, Pastillas, Buje, Rodamientos, Roldanas, Otros" in out
        assert "Errores: 0" in out
        assert "Con cera" not in out and "Kit completo" not in out and "Precio 30" not in out  # notes stay out of the report

    def test_command_errors_exit_non_zero(self, owner, tmp_path, capsys):
        path = write_dump(tmp_path, broken(lambda d: d.update(version=1)))
        for extra in (["--dry-run"], []):
            with pytest.raises(CommandError, match="errores"):
                call_command("garage_import_probikegarage", str(path), "--owner", str(owner.pk), *extra)
            assert "versión 1 no admitida" in capsys.readouterr().out
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(CommandError, match="no es JSON válido"):
            call_command("garage_import_probikegarage", str(bad), "--owner", str(owner.pk), "--dry-run")
        with pytest.raises(CommandError, match="propietario activo"):
            call_command("garage_import_probikegarage", str(path), "--owner", "999999", "--dry-run")
        assert set(owned_rows(owner).values()) == {0}

    def test_apply_query_budget_grows_linearly(self, owner, django_user_model):
        """Reads are one query per table; each write is one domain-service call (lock, ownership and one query per
        CHECK/UNIQUE constraint that full_clean validates), so the cost per row is constant: never O(rows²)."""
        counts = []
        for index, copies in enumerate((5, 15, 25)):
            actor = owner if index == 0 else django_user_model.objects.create_user(f"pbg-budget-{index}", password="synthetic-only")
            with CaptureQueriesContext(connection) as queries:
                apply(actor, scaled_dump(copies), zone=UTC)
            counts.append(len(queries))
        first, second = (counts[1] - counts[0]) / 10, (counts[2] - counts[1]) / 10
        assert first == second and first <= 130, counts  # a component, its mount, rule, intervention and reading
        assert counts[0] - 5 * first <= 120, counts  # categories, the bike and its Strava gear, the type, the rebuild


# Applying --------------------------------------------------------------------------

class TestApply:
    def test_rows(self, owner, imported):
        mapping = imported.mapping
        cats = {c.name: c.icon for c in Category.objects.filter(owner=owner)}
        assert cats == {"Cadena": "chain", "Horquilla de suspensión": "suspension_fork", "Pedales": "pedal", "Calas": "cleat",
                        "Pastillas": "brake", "Buje": "hub", "Rodamientos": "part", "Roldanas": "derailleur", "Otros": "part"}
        bike = Bike.objects.get(owner=owner)
        assert (bike.name, bike.brand, bike.model, bike.notes, str(bike.pk)) == ("Bici sintética", "Marca", "Modelo", "", mapping["bikes"][BIKE])
        gear = StravaGear.objects.get(owner=owner)
        assert (gear.gear_id, gear.name, gear.bike_id) == ("b900001", "Strava sintética", bike.pk)
        assert sorted(Item.objects.filter(owner=owner).values_list("name", flat=True)).count("Pastillas") == 2  # duplicate names kept
        chain = item(owner, "chain", imported)
        assert (chain.notes, chain.brand, chain.purchase_amount, chain.category.name) == ("Precio 30 €", "", None, "Cadena")
        assert Installation.objects.filter(owner=owner).count() == 9 and not Installation.objects.filter(owner=owner, slot__isnull=False).exists()
        cleats = Installation.objects.get(owner=owner, item=item(owner, "cleats", imported))
        assert (cleats.parent_item_id, cleats.bike_id) == (item(owner, "pedals", imported).pk, None)
        fork = Installation.objects.get(owner=owner, item=item(owner, "fork", imported))
        assert (fork.started_at, fork.ended_at, fork.notes) == (when(1, 3, 9), None, SINCE_ALWAYS_NOTE)
        assert set(mapping) >= {"bikes", "components", "installations", "service_intervals", "services", "baselines", "strava_gear"}
        assert len(mapping["services"]["s-kit"]) == 4 and len(mapping["components"]) == 10
        assert imported.report.applied and imported.report.totals["events"] == 9 and "Importado en una sola transacción." in imported.report.lines()

    def test_retired_after_their_mounts(self, owner, imported):
        old = item(owner, "pads_old", imported)
        misc = item(owner, "misc", imported)
        assert old.retired_at == when(2, 1) and Installation.objects.get(item=old).ended_at == when(2, 1)
        assert misc.retired_at == when(3, 1) and Installation.objects.get(item=misc).ended_at == when(3, 1)  # closed by retiring it
        assert item(owner, "pads_new", imported).retired_at is None

    def test_rules_and_lifespan(self, owner, imported):
        chain = item(owner, "chain", imported)
        rule = MaintenanceRule.objects.get(owner=owner, item=chain, service_type__name="Lubricar")
        assert (rule.distance_m, rule.anchor_at, rule.notes) == (Decimal("300000.000"), when(1, 10), "Cera")
        life = lifespan_rule(owner, chain)
        assert is_life(life) and (life.distance_m, life.moving_time_s, life.anchor_at) == (Decimal("3000000.000"), Decimal("360000.000"), when(1, 10))
        mapped = imported.mapping["service_intervals"]
        assert mapped["i-life1"] == mapped["i-life2"] == mapped["i-life3"] == str(life.pk)
        assert ServiceType.objects.filter(owner=owner, name__iexact="max life").count() == 0  # «Max life» is «Vida útil»
        days = MaintenanceRule.objects.get(pk=mapped["i-fork-days"])
        assert (days.calendar_days, days.anchor_at) == (60, when(1, 3, 9))
        bearings = MaintenanceRule.objects.get(pk=mapped["i-bear-elev"])
        assert bearings.elevation_gain_m == Decimal("20000.000") and MaintenanceRule.objects.get(pk=mapped["i-bear-rides"]).ride_count == 10
        assert MaintenanceRule.objects.get(pk=mapped["i-rold"]).anchor_at is None
        # The useful life can be inherited by the replacement chain.
        new = create_inventory(owner, Item, name="Cadena nueva", category=chain.category)
        inherited = inherit_lifespan(owner, outgoing=chain, incoming=new, at=when(3, 20))
        assert is_life(inherited) and (inherited.distance_m, inherited.moving_time_s, inherited.anchor_at) == (
            Decimal("3000000.000"), Decimal("360000.000"), when(3, 20))

    def test_events(self, owner, imported):
        pedals, cleats, fork = (item(owner, key, imported) for key in ("pedals", "cleats", "fork"))
        on_pedals = sorted(ServiceEvent.objects.filter(item=pedals).values_list("service_type__name", "notes", "performed_at"))
        assert on_pedals == sorted((name, "Refresh kit. Kit completo", when(2, 20)) for name in ("Full service", "Check tightness", "Check & lube"))
        assert list(ServiceEvent.objects.filter(item=cleats).values_list("service_type__name", "notes")) == [("Refresh kit", "Kit completo")]
        assert sorted(ServiceEvent.objects.filter(item=fork).values_list("service_type__name", "notes", "performed_at")) == [
            ("Aceite", "", when(1, 20)), ("Aceite", "Servicio.", when(3, 1))]
        measure = ServiceEvent.objects.get(item=item(owner, "pads_new", imported))
        assert (measure.service_type.name, measure.notes, measure.amount, measure.currency) == ("Medición", "1,2 mm", None, None)
        swap = ServiceEvent.objects.get(item=item(owner, "chain", imported), service_type__name=LIFE_TYPE)
        assert (swap.notes, swap.performed_at) == ("Cambio de cadena.", when(1, 10))
        # One type per name without case: «Medición » and the starter-like types are created once.
        names = list(ServiceType.objects.filter(owner=owner).values_list("name", flat=True))
        assert len(names) == len({n.lower() for n in names}) and "Medición" in names

    def test_baselines(self, owner, imported):
        old = item(owner, "pads_old", imported)
        readings = sorted(UsageBaseline.objects.filter(item=old).values_list("metric", "scope", "cut_at", "value", "source", "is_estimated", "notes"))
        assert readings == [("distance_m", "lifetime", when(1, 5), Decimal("1300000.000"), BASELINE_SOURCE, True, ""),
                            ("moving_time_s", "lifetime", when(1, 5), Decimal("298800.000"), BASELINE_SOURCE, True, "")]
        assert UsageBaseline.objects.get(item=item(owner, "roldana", imported)).cut_at == EXPORTED
        assert sorted(imported.mapping["baselines"]) == sorted([C["pads_old"], C["roldana"]])

    def test_reuses_categories_and_types_and_other_owners_stay_apart(self, owner, other):
        create_inventory(owner, Category, name="cadena", icon="tool")
        kind = save_maintenance(owner, ServiceType, name="lubricar")
        foreign = create_inventory(other, Category, name="Pedales")
        result = apply(owner, synthetic_dump(), zone=UTC)
        assert result.report.totals["categories_reused"] == 1 and result.report.reused_categories == ("cadena",)
        assert result.report.reused_types == ("lubricar",)
        chain = item(owner, "chain", result)
        assert chain.category.name == "cadena" and chain.category.icon == "tool"  # an existing icon is never changed
        assert MaintenanceRule.objects.get(item=chain, service_type__name__iexact="lubricar").service_type_id == kind.pk
        assert Category.objects.filter(owner=owner, name__iexact="cadena").count() == 1
        assert item(owner, "pedals", result).category_id != foreign.pk and Category.objects.filter(owner=other).count() == 1

    def test_one_use_only(self, owner, imported):
        with pytest.raises(ImportRejected) as rejected:
            apply(owner, synthetic_dump(), zone=UTC)
        assert "ya tiene 1 bicis y 10 objetos" in rejected.value.report.errors[0]

    def test_logger_gets_counts_only(self, owner, caplog):
        with caplog.at_level(logging.INFO, logger="garage"):
            apply(owner, synthetic_dump(), zone=UTC)
        records = [r.getMessage() for r in caplog.records if r.name.startswith("garage")]
        assert len(records) == 1 and "items=10" in records[0]
        for secret in ("Cadena sintética", "Pastillas", "Precio", "Kit completo", "Bici sintética", "b900001"):
            assert all(secret not in message for message in records)


class TestAtomic:
    def test_a_late_failure_leaves_no_rows(self, owner, monkeypatch):
        def fail(*args, **kwargs):
            raise RuntimeError("simulated late failure")
        monkeypatch.setattr("garage.services.probikegarage_import.rebuild_usage", fail)
        with pytest.raises(RuntimeError, match="simulated"):
            apply(owner, synthetic_dump(), zone=UTC)
        assert set(owned_rows(owner).values()) == {0}

    def test_a_refused_row_is_named_and_rolls_back(self, owner, monkeypatch):
        def refuse(*args, **kwargs):
            raise InventoryWriteError({"retired_at": "Correct later or empty installations explicitly before retiring this resource."})
        monkeypatch.setattr("garage.services.probikegarage_import.retire_inventory", refuse)
        with pytest.raises(ImportFailed) as failed:
            apply(owner, synthetic_dump(), zone=UTC)
        assert f"components {C['pads_old']} «Pastillas»: Garage lo rechazó al escribir" in failed.value.messages[0]
        assert set(owned_rows(owner).values()) == {0}


# Usage, due dates and the verification ------------------------------------------------

def strava_text(strava_id, start, distance, moving, elevation, gear):
    return ('{"id": %d, "athlete": {"id": %d}, "name": "Salida", "sport_type": "Ride", "type": "Ride", "start_date": "%s", '
            '"distance": %d, "moving_time": %d, "elapsed_time": %d, "gear_id": %s, "total_elevation_gain": %d}'
            % (strava_id, ATHLETE, iso(start), distance, moving, moving + 60, json.dumps(gear), elevation))


def strava_history(owner, rides=RIDES):
    """What «Importar histórico» stores: one Strava source per activity, the bike through the linked gear."""
    account = StravaAccount.objects.create(owner=owner, athlete_id=ATHLETE, scopes=ENV_SCOPES)
    with transaction.atomic():
        locked = _lock_owner(owner)
        touched = set()
        for sid, start, distance, moving, elevation, bike in rides:
            store_activity(locked, account, json.loads(strava_text(sid, start, distance, moving, elevation, "b900001" if bike else None),
                                                       parse_float=Decimal), touched=touched)
        rebuild_rides_locked(locked, touched)


class TestUsageAndDue:
    def test_totals_add_the_initial_reading(self, owner, imported):
        bike = Bike.objects.get(owner=owner)
        create_manual_ride(owner, started_at=when(1, 12), bike=bike, distance_m=Decimal(40000), moving_time_s=Decimal(5400))
        create_manual_ride(owner, started_at=when(2, 10), bike=bike, distance_m=Decimal(50000), moving_time_s=Decimal(7200))
        rebuild_usage(owner)
        old, new = item(owner, "pads_old", imported), item(owner, "pads_new", imported)
        distance = summarize_item_usage(owner, old.pk, metric="distance_m", scope="lifetime", at=EXPORTED).reading
        assert distance.total == Decimal("1340000.000") and distance.is_estimated  # 1.300 km read + the ride before retiring
        assert summarize_item_usage(owner, old.pk, metric="moving_time_s", scope="lifetime", at=EXPORTED).reading.total == Decimal("304200.000")
        assert summarize_item_usage(owner, new.pk, metric="distance_m", scope="lifetime", at=EXPORTED).reading.observed == Decimal("50000.000")
        cleats = item(owner, "cleats", imported)  # nested in the pedals
        assert summarize_item_usage(owner, cleats.pk, metric="distance_m", scope="lifetime", at=EXPORTED).reading.observed == Decimal("90000.000")

    def test_due_dates_see_the_imported_interventions(self, owner, imported):
        due = {result.rule.pk: result for result in maintenance_due(owner, at=EXPORTED)}
        mapped = imported.mapping["service_intervals"]
        events = imported.mapping["services"]
        lube = due[MaintenanceRule.objects.get(pk=mapped["i-lube"]).pk]
        assert str(lube.event.pk) in events["s-lube"] and lube.reference_at == when(2, 15)
        oil = due[MaintenanceRule.objects.get(pk=mapped["i-fork-oil"]).pk]
        assert oil.reference_at == when(3, 1) and oil.event.notes == "Servicio."  # the newest «Aceite», not the older one
        for interval_id in ("i-full", "i-tight", "i-clip"):
            assert due[MaintenanceRule.objects.get(pk=mapped[interval_id]).pk].reference_at == when(2, 20)
        life = due[MaintenanceRule.objects.get(pk=mapped["i-life1"]).pk]
        assert life.event.service_type.name == LIFE_TYPE and life.reference_at == when(1, 10)
        assert due[MaintenanceRule.objects.get(pk=mapped["i-rold"]).pk].status == "unknown"  # no reference yet
        days = due[MaintenanceRule.objects.get(pk=mapped["i-fork-days"]).pk]
        assert days.reference_at == when(1, 3, 9) and days.status == "due"  # anchored at its first mount


class TestVerify:
    def run(self, owner, dump, tmp_path, capsys, mapping=None):
        path = write_dump(tmp_path, dump, "verify.json")
        args = ["garage_probikegarage_verify", str(path), "--owner", str(owner.pk)]
        if mapping:
            args += ["--mapping", str(mapping)]
        with CaptureQueriesContext(connection) as queries:
            call_command(*args)
        assert not writes(queries)
        return capsys.readouterr().out

    def test_before_strava_everything_is_zero(self, owner, tmp_path, capsys):
        apply(owner, clean_dump(), zone=UTC)
        out = self.run(owner, clean_dump(), tmp_path, capsys)
        assert "0 de 5 salidas del volcado están en Garage: importa el histórico de Strava" in out
        assert "faltan 5" in out and "filas con diferencias." in out

    def test_no_differences_after_the_strava_history(self, owner, tmp_path, capsys):
        result = apply(owner, clean_dump(), zone=UTC)
        strava_history(owner)
        assert Ride.objects.filter(owner=owner, bike__isnull=False).count() == 4 and ActivitySource.objects.filter(owner=owner).count() == 5
        report = verify(owner, clean_dump(), mapping=read_mapping(json.loads(json.dumps(result.mapping))))
        rows = [row for block in report.blocks for row in block.rows]
        assert [row for row in rows if not row.ok] == [] and report.differences == 0 and report.rides_found == 5
        assert len(rows) == 4 + 10 * 4 + 10  # bikes, components, rules
        # Without the map, by name and category (the two «Pastillas» told apart by their retirement).
        out = self.run(owner, clean_dump(), tmp_path, capsys)
        assert out.rstrip().endswith("Sin diferencias.") and "5 de 5 del volcado están en Garage" in out

    def test_strava_history_first_then_the_import(self, owner):
        """Rides already downloaded from Strava (bike unknown) take their bike when the import links the gear."""
        strava_history(owner)
        assert Ride.objects.filter(owner=owner, bike__isnull=False).count() == 0
        assert StravaGear.objects.filter(owner=owner, gear_id="b900001", bike__isnull=True).exists()
        apply(owner, clean_dump(), zone=UTC)
        assert Ride.objects.filter(owner=owner, bike__isnull=False).count() == 4 and StravaGear.objects.filter(owner=owner).count() == 1
        report = verify(owner, clean_dump())
        assert report.differences == 0, [row for block in report.blocks for row in block.rows if not row.ok]

    def test_differences_are_reported(self, owner, tmp_path, capsys):
        result = apply(owner, synthetic_dump(), zone=UTC)
        strava_history(owner, RIDES[:-1])  # the ride without a bike never arrived
        mapping = tmp_path / "map.json"
        mapping.write_text(json.dumps(result.mapping), encoding="utf-8")
        out = self.run(owner, synthetic_dump(), tmp_path, capsys, mapping=mapping)
        assert "falta la actividad 7005 del 20/03/2026 10:00" in out
        failing = [line for line in out.splitlines() if "← diferencia" in line]
        # On purpose: the initial elevation is not stored and a second «Max life» keeps the first threshold.
        assert len(failing) == 2, failing
        assert any("Pastillas" in line and " m " in line for line in failing) and any("Max life" in line for line in failing)
        # A rule of a part never mounted with nothing used (R043-2): «Sin datos» in Garage, the whole interval in ProBikeGarage.
        limpiar = [line for line in out.splitlines() if "· Limpiar" in line]
        assert len(limpiar) == 1 and "sin montar" in limpiar[0] and "← diferencia" not in limpiar[0]
        assert "3 filas con diferencias." in out

    def test_a_changed_ride_is_a_difference(self, owner):
        apply(owner, clean_dump(), zone=UTC)
        changed = list(RIDES)
        changed[1] = (7002, when(1, 12), 41000, 5400, 500, True)  # 1 km more than ProBikeGarage counted
        strava_history(owner, changed)
        report = verify(owner, clean_dump())
        bad = {(row.label, row.kind) for block in report.blocks for row in block.rows if not row.ok}
        assert ("Bici sintética", "distance") in bad and ("Cadena sintética · Cadena", "distance") in bad
        assert ("Cadena sintética · Lubricar", "distance") not in bad  # that ride came before the last lubrication


class TestMappingFile:
    def test_written_outside_the_repository_once(self, owner, tmp_path, capsys):
        path = write_dump(tmp_path, synthetic_dump())
        inside = Path(settings.BASE_DIR) / "garage-mapping-test.json"
        with pytest.raises(CommandError, match="fuera del repositorio"):
            call_command("garage_import_probikegarage", str(path), "--owner", str(owner.pk), "--mapping", str(inside))
        assert not inside.exists() and set(owned_rows(owner).values()) == {0}
        existing = tmp_path / "taken.json"
        existing.write_text("{}", encoding="utf-8")
        with pytest.raises(CommandError, match="ya existe"):
            call_command("garage_import_probikegarage", str(path), "--owner", str(owner.pk), "--mapping", str(existing))
        assert set(owned_rows(owner).values()) == {0}
        target = tmp_path / "map.json"
        call_command("garage_import_probikegarage", str(path), "--owner", str(owner.pk), "--mapping", str(target))
        assert f"Mapa guardado en {target.resolve()}" in capsys.readouterr().out
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
        saved = json.loads(target.read_text(encoding="utf-8"))
        assert saved["format"] == "probikegarage-mapping" and saved["bikes"][BIKE] == str(Bike.objects.get(owner=owner).pk)
        assert read_mapping(saved)["components"][C["chain"]] == Item.objects.get(owner=owner, name="Cadena sintética").pk
        text = target.read_text(encoding="utf-8")
        assert "Cadena sintética" not in text and "Precio" not in text  # ids only, no names or notes
