"""garage-030 phase 3 (garage-037): elevation gain and power as ride data.

Synthetic FIT bytes (built like tests_fit_import) and literal Strava JSON only.
"""
import csv
import io
import json
import struct
from datetime import datetime, timedelta, timezone as datetime_timezone
from decimal import Decimal
from zipfile import ZipFile

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .importers.fit import PARSER_VERSION, import_fit, parse_fit
from .models import (SNOOZE_AMOUNTS, THRESHOLD_FIELDS, ActivitySource, ItemUsage, MaintenanceRule, MaintenanceSnooze, Ride,
                     ServiceType)
from .ride_values import (CORE_METRICS, METRIC_FIELDS, PLAUSIBLE_MAX, POWER_METRICS, RIDE_FIELDS, RIDE_METRICS, SOURCE_FIELDS,
                          USAGE_METRICS, decode_manual, encode_manual, plausible, validate_provenance)
from .services.export import ADDED_METRICS, RIDE_COLUMNS, csv_zip, export_snapshot
from .services.import_history import coverage, history_queryset
from .services.installations import create_installation
from .services.lifespan import inherit_lifespan, set_lifespan
from .services.maintenance import save_maintenance
from .services.ownership import InventoryWriteError
from .services.rides import clear_manual_corrections, correct_ride, create_manual_ride, import_fit_session
from .services.snoozes import snooze_rule
from .services.strava_sources import MEASUREMENT_FIELDS, parse_activity, remove_strava_data
from .services.usage import rebuild_usage
from .tests_fit_import import activity, session, uint32
from .tests_strava_client import activity_text, at
from .tests_strava_sources import g, item, store, strava_source  # noqa: F401 (fixture g)
from .validators import MAX_USAGE_VALUE

NEW_FIELDS = ("elevation_gain_m", "average_power_w", "max_power_w", "weighted_power_w", "energy_kj")
# Strava extras: a power meter's readings (device_watts true).
POWER = (', "device_watts": true, "average_watts": 187.4, "max_watts": 812, "weighted_average_watts": 201, '
         '"kilojoules": 1234.5')
LONG_AGO = datetime(2020, 1, 1, tzinfo=datetime_timezone.utc)


def uint16(number, value):
    return (number, 0x84, struct.pack('<H', value))


def fit_power(avg=215, peak=1234, ascent=987, normalized=240, work=1234567):
    """Session fields 20 avg_power, 21 max_power, 22 total_ascent, 34 normalized_power, 48 total_work (J)."""
    return [uint16(20, avg), uint16(21, peak), uint16(22, ascent), uint16(34, normalized), uint32(48, work)]


def phase3(obj):
    return tuple(getattr(obj, field) for field in NEW_FIELDS)


def parsed_values(extra=""):
    return parse_activity(json.loads(activity_text(5, start=at(), extra=extra), parse_float=Decimal)).values


def mounted(g, *names):
    items = [item(g, name) for name in names]
    for obj in items:
        create_installation(g.owner, item=obj, bike=g.gravel, started_at=LONG_AGO)
    return items


# Metric tuples ---------------------------------------------------------------

def test_metric_tuples_split_usage_from_power():
    assert CORE_METRICS == ("distance_m", "moving_time_s", "timer_time_s", "elapsed_time_s")
    assert USAGE_METRICS == (*CORE_METRICS, "elevation_gain_m") and METRIC_FIELDS is USAGE_METRICS
    assert POWER_METRICS == ("average_power_w", "max_power_w", "weighted_power_w", "energy_kj")
    assert RIDE_METRICS == (*USAGE_METRICS, *POWER_METRICS)
    assert set(RIDE_METRICS) <= set(SOURCE_FIELDS) <= set(RIDE_FIELDS)
    assert ADDED_METRICS == NEW_FIELDS and set(PLAUSIBLE_MAX) == set(NEW_FIELDS)
    assert set(RIDE_METRICS) <= MEASUREMENT_FIELDS


def test_plausibility_bounds_make_glitches_unknown():
    for field, limit in PLAUSIBLE_MAX.items():
        assert plausible(field, limit) == limit and plausible(field, limit + Decimal("0.001")) is None
        assert plausible(field, Decimal("0")) == Decimal("0") and plausible(field, None) is None
    assert PLAUSIBLE_MAX == {"elevation_gain_m": Decimal("20000"), "average_power_w": Decimal("2500"), "max_power_w": Decimal("5000"),
                             "weighted_power_w": Decimal("2500"), "energy_kj": Decimal("50000")}
    assert plausible("distance_m", Decimal("900000")) == Decimal("900000")  # only phase-3 metrics have a bound


def test_manual_codec_and_provenance_cover_the_new_fields():
    encoded = encode_manual({"elevation_gain_m": Decimal("12.5"), "energy_kj": None, "max_power_w": "800"})
    assert encoded == {"elevation_gain_m": "12.500", "energy_kj": None, "max_power_w": "800.000"}
    assert decode_manual(encoded) == {"elevation_gain_m": Decimal("12.500"), "energy_kj": None, "max_power_w": Decimal("800.000")}
    for broken in ({"average_power_w": 1.5}, {"weighted_power_w": "-1"}, {"energy_kj": "1.0001"}):
        with pytest.raises(ValidationError):
            encode_manual(broken)
    with pytest.raises(ValidationError):
        decode_manual({"elevation_gain_m": 12})  # stored decimals are exact strings
    validate_provenance({field: {"kind": "unknown", "source_id": None, "updated_at": None} for field in NEW_FIELDS})


# FIT parser --------------------------------------------------------------------

def test_fit_session_reads_elevation_power_and_work():
    row = parse_fit(activity(session(extra=fit_power()))).sessions[0]
    assert phase3(row) == (Decimal("987"), Decimal("215"), Decimal("1234"), Decimal("240"), Decimal("1234.567"))
    assert str(row.energy_kj) == "1234.567"  # joules to kilojoules, exact, three decimals
    assert {field: row.observations()[field] for field in NEW_FIELDS} == dict(zip(NEW_FIELDS, phase3(row)))
    assert parse_fit(activity()).parser_version == PARSER_VERSION == "fitdecode-0.11.0-m2"
    absent = parse_fit(activity(session())).sessions[0]
    assert phase3(absent) == (None,) * 5
    flat = parse_fit(activity(session(extra=fit_power(ascent=0, work=0)))).sessions[0]
    assert flat.elevation_gain_m == Decimal("0") and flat.energy_kj == Decimal("0")  # zero is a known value


def test_fit_invalid_sentinels_are_unknown():
    row = parse_fit(activity(session(extra=fit_power(0xFFFF, 0xFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF)))).sessions[0]
    assert phase3(row) == (None,) * 5
    assert row.distance_m == Decimal("1234567.89")  # the rest of the session is unaffected


def test_fit_implausible_values_are_unknown_never_an_error():
    edge = parse_fit(activity(session(extra=fit_power(2500, 5000, 20000, 2500, 50_000_000)))).sessions[0]
    assert phase3(edge) == (Decimal("20000"), Decimal("2500"), Decimal("5000"), Decimal("2500"), Decimal("50000"))
    beyond = parse_fit(activity(session(extra=fit_power(2501, 5001, 20001, 2501, 50_000_001)))).sessions[0]
    assert phase3(beyond) == (None,) * 5 and beyond.distance_m == Decimal("1234567.89")


def test_fit_malformed_optional_fields_are_unknown_never_an_error():
    """Code review: before phase 3 these fields were ignored and such a file imported; it still must."""
    repeated = parse_fit(activity(session(extra=[uint16(20, 100), uint16(20, 200), uint16(21, 900), uint16(22, 300), uint16(22, 300)]))).sessions[0]
    assert (repeated.average_power_w, repeated.max_power_w, repeated.elevation_gain_m) == (None, Decimal("900"), None)
    as_float = parse_fit(activity(session(extra=[(20, 0x88, struct.pack('<f', 215.5)), uint16(22, 987)]))).sessions[0]
    assert (as_float.average_power_w, as_float.elevation_gain_m) == (None, Decimal("987"))
    as_array = parse_fit(activity(session(extra=[(48, 0x86, struct.pack('<II', 1000, 2000)), (34, 0x84, struct.pack('<HH', 1, 2))]))).sessions[0]
    assert (as_array.energy_kj, as_array.weighted_power_w) == (None, None)
    for row in (repeated, as_float, as_array):
        assert (row.distance_m, row.sport_type) == (Decimal("1234567.89"), "cycling"), "the rest of the session is unaffected"
    with pytest.raises(ValidationError) as caught:
        parse_fit(activity(session(extra=[uint32(9, 4), uint16(20, 100)])))
    assert caught.value.code == "fit_duplicate_field", "a repeated core field still rejects the file"


@pytest.mark.django_db
def test_fit_with_a_malformed_power_field_still_imports(g):
    result = import_fit(g.owner, activity(session(extra=[(20, 0x88, struct.pack('<f', 215.5)), uint16(21, 812), uint16(21, 813),
                                                         uint16(22, 640)])))
    source = ActivitySource.objects.get(pk=result.sessions[0].source_id)
    assert phase3(source) == (Decimal("640"), None, None, None, None)
    assert Ride.objects.get(pk=result.sessions[0].ride_id).elevation_gain_m == Decimal("640")


@pytest.mark.django_db
def test_reimporting_a_file_read_by_the_old_parser_refreshes_its_source_and_usage(g):
    raw = activity(session(extra=fit_power()))
    parsed = parse_fit(raw)
    # As imported before phase 3: same file and session, only the original observations.
    old = {field: value for field, value in parsed.sessions[0].observations().items() if field not in NEW_FIELDS}
    ride, source = import_fit_session(g.owner, file_hash=parsed.file_hash, session_index=0, parser_version="fitdecode-0.11.0",
                                      observations=old)
    (chain,) = mounted(g, "Cadena")
    correct_ride(g.owner, ride.pk, bike=g.gravel.pk)
    assert ItemUsage.objects.get(item=chain).elevation_gain_m is None and phase3(Ride.objects.get()) == (None,) * 5
    stamp = source.observations_updated_at
    result = import_fit(g.owner, raw)
    source.refresh_from_db()
    assert result.sessions[0].source_id == source.pk and result.sessions[0].ride_id == ride.pk
    assert ActivitySource.objects.count() == 1 and Ride.objects.count() == 1
    assert source.parser_version == PARSER_VERSION and source.observations_updated_at > stamp
    assert phase3(source) == (Decimal("987"), Decimal("215"), Decimal("1234"), Decimal("240"), Decimal("1234.567"))
    ride = Ride.objects.get()
    assert phase3(ride) == phase3(source) and ride.bike_id == g.gravel.pk
    assert all(ride.field_provenance[field] == {"kind": "fit", "source_id": str(source.pk),
                                                 "updated_at": source.observations_updated_at.isoformat()} for field in NEW_FIELDS)
    assert ItemUsage.objects.get(item=chain).elevation_gain_m == Decimal("987")
    # Importing it again changes nothing.
    import_fit(g.owner, raw)
    assert ActivitySource.objects.get().observations_updated_at == source.observations_updated_at


# Strava adapter ----------------------------------------------------------------

def test_strava_power_only_from_a_power_meter():
    measured = parsed_values(POWER)
    assert tuple(measured[field] for field in NEW_FIELDS) == (Decimal("12.300"), Decimal("187.400"), Decimal("812.000"),
                                                               Decimal("201.000"), Decimal("1234.500"))
    for extra in (POWER.replace("true", "false"), POWER.replace(', "device_watts": true', ""), POWER.replace("true", '"true"'), ""):
        values = parsed_values(extra)
        assert values["elevation_gain_m"] == Decimal("12.300")  # elevation is always observed
        assert all(values[field] is None for field in POWER_METRICS)


def test_strava_implausible_or_inexact_values_are_unknown():
    values = parsed_values(', "total_elevation_gain": 20000.1, "device_watts": true, "average_watts": 2500.1, "max_watts": 5000, '
                           '"weighted_average_watts": 2501, "kilojoules": 50000.001')
    assert (values["elevation_gain_m"], values["average_power_w"], values["max_power_w"], values["weighted_power_w"],
            values["energy_kj"]) == (None, None, Decimal("5000.000"), None, None)
    values = parsed_values(', "total_elevation_gain": 20000, "device_watts": true, "average_watts": -1, "kilojoules": 1.0001')
    assert values["elevation_gain_m"] == Decimal("20000.000") and values["average_power_w"] is None and values["energy_kj"] is None


@pytest.mark.django_db
def test_observing_a_phase_two_source_again_fills_elevation_and_power(g):
    (chain,) = mounted(g, "Cadena")
    assert store(g, 7, start=at(), extra=POWER).kind == "imported"
    # A Strava source stored before migration 0012 has no elevation or power yet.
    ActivitySource.objects.filter(external_id=7).update(**dict.fromkeys(NEW_FIELDS))
    ride = Ride.objects.get()
    correct_ride(g.owner, ride.pk, bike=g.gravel.pk)  # recalculates from the old observation
    assert phase3(Ride.objects.get()) == (None,) * 5 and ItemUsage.objects.get(item=chain).elevation_gain_m is None
    assert store(g, 7, start=at(), extra=POWER).kind == "updated"
    source = strava_source(7)
    assert phase3(source) == (Decimal("12.300"), Decimal("187.400"), Decimal("812.000"), Decimal("201.000"), Decimal("1234.500"))
    ride = Ride.objects.get()
    assert phase3(ride) == phase3(source)
    assert {ride.field_provenance[field]["kind"] for field in NEW_FIELDS} == {"strava"}
    assert ItemUsage.objects.get(item=chain).elevation_gain_m == Decimal("12.300")
    assert store(g, 7, start=at(), extra=POWER).kind == "unchanged"
    # The meter disappears on Strava (device_watts false): the power becomes unknown, elevation stays.
    assert store(g, 7, start=at(), extra=POWER.replace("true", "false")).kind == "updated"
    assert phase3(Ride.objects.get()) == (Decimal("12.300"), None, None, None, None)


# Precedence and manual corrections ---------------------------------------------

@pytest.mark.django_db
def test_fit_measures_strava_fills_and_manual_beats_both(g):
    fit_ride, fit_source = import_fit_session(g.owner, file_hash="c" * 64, session_index=0, parser_version=PARSER_VERSION,
                                              observations={"started_at": at(), "sport_type": "cycling", "distance_m": Decimal("30000"),
                                                            "average_power_w": Decimal("190")})
    store(g, 8, start=at(), extra=POWER)
    ride = Ride.objects.get()
    source = strava_source(8)
    assert ride.pk == fit_ride.pk and source.ride_id == ride.pk
    assert ride.average_power_w == Decimal("190") and ride.field_provenance["average_power_w"]["source_id"] == str(fit_source.pk)
    assert ride.elevation_gain_m == Decimal("12.300") and ride.field_provenance["elevation_gain_m"]["source_id"] == str(source.pk)
    assert ride.max_power_w == Decimal("812") and ride.field_provenance["max_power_w"]["kind"] == "strava"
    ride = correct_ride(g.owner, ride.pk, elevation_gain_m=None, energy_kj=Decimal("999.999"))
    assert ride.elevation_gain_m is None and ride.energy_kj == Decimal("999.999")
    assert ride.field_provenance["elevation_gain_m"]["kind"] == ride.field_provenance["energy_kj"]["kind"] == "manual"
    store(g, 8, start=at(), extra=POWER.replace("187.4", "188"))  # a newer observation never beats a correction
    ride = Ride.objects.get()
    assert ride.elevation_gain_m is None and ride.energy_kj == Decimal("999.999")
    ride = clear_manual_corrections(g.owner, ride.pk, fields=["elevation_gain_m", "energy_kj"])
    assert ride.elevation_gain_m == Decimal("12.300") and ride.energy_kj == Decimal("1234.500")


@pytest.mark.django_db
def test_a_typed_elevation_or_power_keeps_a_strava_only_ride(g):
    store(g, 9, start=at())
    store(g, 10, start=at() + timedelta(days=1))
    kept, dropped = Ride.objects.order_by("started_at")
    correct_ride(g.owner, kept.pk, average_power_w=Decimal("200"))
    result = remove_strava_data(g.owner)
    assert (result.deleted_rides, result.kept_rides) == (1, 1)
    assert Ride.objects.filter(pk=kept.pk).exists() and not Ride.objects.filter(pk=dropped.pk).exists()


@pytest.mark.django_db
def test_unknown_elevation_or_power_never_makes_a_ride_pending(g):
    ride = create_manual_ride(g.owner, started_at=at(), sport_type="cycling", bike=g.gravel.pk, distance_m=Decimal("1"),
                              moving_time_s=Decimal("1"), timer_time_s=Decimal("1"), elapsed_time_s=Decimal("1"))
    assert phase3(ride) == (None,) * 5
    assert not history_queryset(g.owner, pending=True).exists()
    stats = coverage(g.owner)
    assert set(stats["missing_fields"]) == set(CORE_METRICS) and stats["observed"] == 1


# Materialization ---------------------------------------------------------------

@pytest.mark.django_db
def test_elevation_flows_whole_to_every_resolved_item_and_rebuilds(g):
    chain, helmet = mounted(g, "Cadena", "Casco")
    ride = create_manual_ride(g.owner, started_at=at(), bike=g.gravel.pk, distance_m=Decimal("1000"),
                              elevation_gain_m=Decimal("345.5"), average_power_w=Decimal("180"))
    facts = list(ItemUsage.objects.filter(ride=ride))
    assert {fact.item_id for fact in facts} == {chain.pk, helmet.pk}
    assert all(fact.elevation_gain_m == Decimal("345.500") and fact.distance_m == Decimal("1000") for fact in facts)
    assert not set(POWER_METRICS) & {field.name for field in ItemUsage._meta.get_fields()}  # power is never materialized
    ItemUsage.objects.update(elevation_gain_m=None)  # stale facts
    assert rebuild_usage(g.owner).updated == 2
    assert set(ItemUsage.objects.values_list("elevation_gain_m", flat=True)) == {Decimal("345.500")}
    assert rebuild_usage(g.owner).updated == 0
    correct_ride(g.owner, ride.pk, elevation_gain_m=None)
    assert set(ItemUsage.objects.values_list("elevation_gain_m", flat=True)) == {None}
    correct_ride(g.owner, ride.pk, average_power_w=Decimal("250"))  # power changes no usage fact
    assert rebuild_usage(g.owner, dry_run=True).updated == 0


@pytest.mark.django_db
def test_item_usage_elevation_has_its_own_check(g):
    (chain,) = mounted(g, "Cadena")
    create_manual_ride(g.owner, started_at=at(), bike=g.gravel.pk, elevation_gain_m=Decimal("10"))
    fact = ItemUsage.objects.get(item=chain)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        ItemUsage.objects.filter(pk=fact.pk).update(elevation_gain_m=Decimal("-1"))
    assert error.value.__cause__.diag.constraint_name == "garage_itemusage_elevation_gain_m_valid"
    fact.elevation_gain_m = Decimal("1.0001")
    with pytest.raises(ValidationError):
        fact.full_clean()


# Rules, snoozes and useful life ------------------------------------------------

def _sql_error(model, pk, **values):
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        model.objects.filter(pk=pk).update(**values)
    return error.value.__cause__.diag.constraint_name


@pytest.mark.django_db
def test_rule_and_snooze_accept_elevation_alone_and_reject_non_positive(g):
    assert THRESHOLD_FIELDS == SNOOZE_AMOUNTS and "elevation_gain_m" in SNOOZE_AMOUNTS
    kind = save_maintenance(g.owner, ServiceType, name="Revisión")
    (chain,) = mounted(g, "Cadena")
    rule = save_maintenance(g.owner, MaintenanceRule, item=chain, service_type=kind, elevation_gain_m=Decimal("10000"), anchor_at=at())
    assert rule.elevation_gain_m == Decimal("10000") and rule.distance_m is None
    for bad in (Decimal("0"), Decimal("-1"), Decimal("1.0001"), 1.5, MAX_USAGE_VALUE + 1):
        with pytest.raises(InventoryWriteError):
            save_maintenance(g.owner, MaintenanceRule, rule.pk, elevation_gain_m=bad)
    with pytest.raises(InventoryWriteError):
        save_maintenance(g.owner, MaintenanceRule, rule.pk, elevation_gain_m=None)  # no threshold left
    assert _sql_error(MaintenanceRule, rule.pk, elevation_gain_m=0) == "garage_rule_elevation_gain_m_positive"
    assert _sql_error(MaintenanceRule, rule.pk, elevation_gain_m=None) == "garage_maintenancerule_has_threshold"
    snooze = snooze_rule(g.owner, rule, elevation_gain_m=Decimal("500"))
    assert snooze.elevation_gain_m == Decimal("500") and snooze.distance_m is None and snooze.calendar_days is None
    with pytest.raises(InventoryWriteError):
        snooze_rule(g.owner, rule, elevation_gain_m=Decimal("0"))
    assert _sql_error(MaintenanceSnooze, snooze.pk, elevation_gain_m=0) == "garage_snooze_elevation_gain_m_positive"
    assert _sql_error(MaintenanceSnooze, snooze.pk, elevation_gain_m=None) == "garage_snooze_has_amount"


@pytest.mark.django_db
def test_useful_life_writes_and_hands_over_its_elevation(g):
    old, new = mounted(g, "Cadena vieja", "Cadena nueva")
    rule = set_lifespan(g.owner, old, distance_m=Decimal("3000000"), elevation_gain_m=Decimal("40000"), start=at())
    assert (rule.distance_m, rule.elevation_gain_m) == (Decimal("3000000"), Decimal("40000"))
    inherited = inherit_lifespan(g.owner, outgoing=old, incoming=new, at=at(2))
    assert (inherited.distance_m, inherited.elevation_gain_m, inherited.anchor_at) == (Decimal("3000000"), Decimal("40000"), at(2))
    rule = set_lifespan(g.owner, old, elevation_gain_m=Decimal("1"), start=at())
    assert (rule.distance_m, rule.elevation_gain_m) == (None, Decimal("1"))  # elevation alone is a useful life


# Export ------------------------------------------------------------------------

@pytest.mark.django_db
def test_export_adds_elevation_and_power_last_with_units(g):
    ride, source = import_fit_session(g.owner, file_hash="d" * 64, session_index=0, parser_version=PARSER_VERSION,
                                      observations={"started_at": at(), "sport_type": "cycling", "distance_m": Decimal("1000"),
                                                    "elevation_gain_m": Decimal("987"), "average_power_w": Decimal("215.5")})
    old = create_manual_ride(g.owner, started_at=at(3), distance_m=Decimal("5"))
    # A ride saved before phase 3 has no provenance for the new fields yet.
    Ride.objects.filter(pk=old.pk).update(field_provenance={key: value for key, value in old.field_provenance.items()
                                                            if key not in NEW_FIELDS})
    kind = save_maintenance(g.owner, ServiceType, name="Revisión")
    rule = save_maintenance(g.owner, MaintenanceRule, bike=g.gravel, service_type=kind, elevation_gain_m=Decimal("8000"), anchor_at=at())
    snooze_rule(g.owner, rule, elevation_gain_m=Decimal("700"))
    snapshot = export_snapshot(g.owner)
    units = snapshot["units"]
    assert (units["elevation_gain_m"], units["average_power_w"], units["max_power_w"], units["weighted_power_w"],
            units["energy_kj"]) == ("metres", "watts", "watts", "watts", "kilojoules")
    rides = {row["id"]: row for row in snapshot["tables"]["rides"]}
    measured = rides[str(ride.pk)]
    assert measured["elevation_gain_m"] == "987.000" and measured["average_power_w"] == "215.500"
    assert measured["field_provenance"]["elevation_gain_m"] == {"kind": "fit", "source_id": str(source.pk),
                                                                "updated_at": measured["field_provenance"]["elevation_gain_m"]["updated_at"]}
    assert {"max_power_w", "weighted_power_w", "energy_kj"} <= set(measured["excluded_fields"]) and "max_power_w" not in measured
    legacy = rides[str(old.pk)]
    assert set(NEW_FIELDS) <= set(legacy["excluded_fields"]) and not set(NEW_FIELDS) & set(legacy)
    exported_source = snapshot["tables"]["sources"][0]
    assert exported_source["elevation_gain_m"] == "987.000" and exported_source["energy_kj"] is None
    assert snapshot["tables"]["maintenance_rules"][0]["elevation_gain_m"] == "8000.000"
    assert snapshot["tables"]["snoozes"][0]["elevation_gain_m"] == "700.000"
    with ZipFile(io.BytesIO(csv_zip(snapshot))) as archive:
        headers = {name: next(csv.reader(io.StringIO(archive.read(name + ".csv").decode())))
                   for name in ("rides", "sources", "maintenance_rules", "snoozes")}
        rows = {row["id"]: row for row in csv.DictReader(io.StringIO(archive.read("rides.csv").decode()))}
    # Old columns keep their positions; the new ones come last.
    assert headers["rides"] == ["id", "created_at", "updated_at", "started_at", "name", "sport_type", "distance_m", "moving_time_s",
                                "timer_time_s", "elapsed_time_s", "notes", "bike_id", "manual_overrides", "field_provenance",
                                "excluded_fields", *NEW_FIELDS] == ["id", "created_at", "updated_at", *RIDE_COLUMNS]
    assert headers["sources"][-5:] == list(NEW_FIELDS) and headers["sources"][-9:-5] == list(CORE_METRICS)
    assert headers["maintenance_rules"][-2:] == ["notes", "elevation_gain_m"] and headers["snoozes"][-2:] == ["notes", "elevation_gain_m"]
    assert rows[str(ride.pk)]["elevation_gain_m"] == "987.000" and rows[str(ride.pk)]["max_power_w"] == r"\N"
