from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as datetime_timezone, timedelta
from decimal import Decimal
from threading import Barrier
from types import SimpleNamespace
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models.deletion import ProtectedError

from .models import ActivitySource, Bike, ImportRun, Ride
from .ride_values import RIDE_METRICS, SOURCE_FIELDS
from .services.ownership import InventoryNotFound, create_inventory, get_inventory, scoped_inventory
from .services.rides import (clear_manual_corrections, correct_ride, create_import_run, create_manual_ride,
                             delete_ride, import_fit_session, withdraw_source)


def instant(day=1):
    return datetime(2026, 1, day, tzinfo=datetime_timezone.utc)


@pytest.fixture
def rides(db, django_user_model):
    owner = django_user_model.objects.create_user(username="ride-owner")
    other = django_user_model.objects.create_user(username="ride-other")
    return SimpleNamespace(owner=owner, other=other, bike=create_inventory(owner, Bike, name="Own bike"),
                           foreign_bike=create_inventory(other, Bike, name="SECRET bike"))


def imported(owner, /, *, file_hash="a" * 64, session_index=0, ride_id=None, **observations):
    return import_fit_session(owner, file_hash=file_hash, session_index=session_index, parser_version="fixture-1.0",
                              observations={"started_at": instant(), **observations}, ride_id=ride_id)


@pytest.mark.django_db
def test_manual_ride_has_own_uuid_explicit_unknowns_and_provenance(rides):
    ride = create_manual_ride(rides.owner, started_at=instant(), name="Manual", bike=rides.bike,
                              distance_m=Decimal("0"), timer_time_s=Decimal("12.345"), notes="Own notes")
    assert ride.owner == rides.owner and isinstance(ride.pk, uuid.UUID)
    assert ride.has_known_start and ride.bike == rides.bike and ride.distance_m == Decimal("0")
    assert ride.moving_time_s is None and ride.elapsed_time_s is None
    assert ride.field_provenance["distance_m"]["kind"] == "manual"
    assert ride.field_provenance["moving_time_s"]["kind"] == "unknown"
    assert not ActivitySource.objects.exists()


@pytest.mark.django_db
def test_file_ride_without_any_provider_or_bike_keeps_timer_distinct(rides):
    ride, source = imported(rides.owner, timer_time_s="123.456", elapsed_time_s="150.001", sport_type="cycling")
    assert ride.bike is None and ride.moving_time_s is None
    assert ride.timer_time_s == Decimal("123.456") and ride.elapsed_time_s == Decimal("150.001")
    assert source.ride_id == ride.pk and source.owner == rides.owner
    assert ride.field_provenance["timer_time_s"]["source_id"] == str(source.pk)


@pytest.mark.django_db
def test_hash_session_identity_is_owner_scoped_and_not_matching_by_time(rides):
    first, source = imported(rides.owner)
    repeat, repeated_source = imported(rides.owner)
    other, _ = imported(rides.other)
    different_session, _ = imported(rides.owner, session_index=1)
    different_hash, _ = imported(rides.owner, file_hash="b" * 64)
    assert repeat.pk == first.pk and repeated_source.pk == source.pk
    assert len({first.pk, other.pk, different_session.pk, different_hash.pk}) == 4
    assert Ride.objects.count() == ActivitySource.objects.count() == 4


@pytest.mark.django_db
def test_exact_retry_and_metadata_change_preserve_source_precedence(rides):
    ride, first = imported(rides.owner, distance_m="100")
    ride, second = imported(rides.owner, file_hash="b" * 64, ride_id=ride.pk, distance_m="200")
    first_stamp = first.observations_updated_at
    run = create_import_run(rides.owner)
    ride, retried = import_fit_session(rides.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-2",
        observations={"started_at": instant(), "distance_m": Decimal("100.0000")}, import_run_id=run.pk)
    assert retried.observations_updated_at == first_stamp
    assert retried.import_run_id == run.pk and retried.parser_version == "fixture-2"
    assert ride.distance_m == Decimal("200") and ride.field_provenance["distance_m"]["source_id"] == str(second.pk)
    ride, changed = imported(rides.owner, distance_m="101")
    assert changed.observations_updated_at > first_stamp and ride.distance_m == Decimal("101")


@pytest.mark.django_db
def test_source_snapshot_replaces_missing_fields_and_other_known_source_is_fallback(rides):
    ride, first = imported(rides.owner, distance_m="100", moving_time_s="50.125")
    ride, second = imported(rides.owner, file_hash="b" * 64, ride_id=ride.pk, distance_m="200")
    assert ride.distance_m == Decimal("200") and ride.moving_time_s == Decimal("50.125")
    ride, first = imported(rides.owner, timer_time_s="30")
    assert first.distance_m is None and first.moving_time_s is None
    assert ride.distance_m == Decimal("200") and ride.moving_time_s is None and ride.timer_time_s == Decimal("30")
    ride = withdraw_source(rides.owner, second.pk)
    assert ride.distance_m is None and ride.timer_time_s == Decimal("30")


@pytest.mark.django_db
def test_manual_corrections_including_null_survive_reimports_and_source_withdrawal(rides):
    ride, source = imported(rides.owner, distance_m="100", moving_time_s="60")
    ride = correct_ride(rides.owner, ride.pk, distance_m=None, moving_time_s="12.345", bike=rides.bike,
                        name="My corrected ride", notes="Own retained notes")
    assert "distance_m" in ride.manual_overrides and ride.manual_overrides["distance_m"] is None
    ride, _ = imported(rides.owner, distance_m="200", moving_time_s="70")
    assert ride.distance_m is None and ride.moving_time_s == Decimal("12.345")
    ride = withdraw_source(rides.owner, source.pk)
    assert ride.started_at is None and not ride.has_known_start
    assert ride.distance_m is None and ride.moving_time_s == Decimal("12.345")
    assert ride.bike == rides.bike and ride.name == "My corrected ride" and ride.notes == "Own retained notes"
    assert Ride.objects.filter(pk=ride.pk).exists()
    with pytest.raises(ValidationError) as error:
        imported(rides.owner, distance_m="300")
    assert error.value.error_dict["reactivate"][0].code == "source_withdrawn"
    restored, _ = import_fit_session(rides.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
        observations={"started_at": instant(), "distance_m": "300"}, reactivate=True)
    assert restored.has_known_start and restored.distance_m is None and restored.moving_time_s == Decimal("12.345")


@pytest.mark.django_db
def test_withdraw_latest_source_recalculates_remaining_and_never_deletes_ride(rides):
    ride, first = imported(rides.owner, distance_m="100")
    ride, second = imported(rides.owner, file_hash="b" * 64, ride_id=ride.pk, started_at=instant(2), distance_m="200")
    restored = withdraw_source(rides.owner, second.pk)
    assert restored.started_at == instant() and restored.distance_m == Decimal("100")
    again = withdraw_source(rides.owner, second.pk)
    assert again.pk == ride.pk and again.distance_m == Decimal("100")
    unknown = withdraw_source(rides.owner, first.pk)
    assert unknown.started_at is None and unknown.distance_m is None and not unknown.has_known_start
    assert Ride.objects.count() == 1 and ActivitySource.objects.count() == 2


@pytest.mark.django_db
def test_explicit_clear_correction_restores_source_and_manual_only_start_is_protected(rides):
    ride, source = imported(rides.owner, distance_m="100")
    correct_ride(rides.owner, ride.pk, distance_m=None)
    restored = clear_manual_corrections(rides.owner, ride.pk, fields=["distance_m"])
    assert restored.distance_m == Decimal("100") and "distance_m" not in restored.manual_overrides
    manual = create_manual_ride(rides.owner, started_at=instant(), notes="Preserve")
    with pytest.raises(ValidationError):
        clear_manual_corrections(rides.owner, manual.pk, fields=["started_at", "notes"])
    manual.refresh_from_db()
    assert manual.started_at == instant() and manual.notes == "Preserve"


@pytest.mark.parametrize("field", RIDE_METRICS)
@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("NaN"), Decimal("Infinity"), Decimal("1.2345"), 0.1, True,
                                       Decimal("100000000000000000")])
@pytest.mark.django_db
def test_manual_and_fit_reject_inexact_nonfinite_or_float_metrics(field, value, rides):
    with pytest.raises(ValidationError):
        create_manual_ride(rides.owner, started_at=instant(), **{field: value})
    with pytest.raises(ValidationError):
        imported(rides.owner, **{field: value})
    assert not Ride.objects.exists() and not ActivitySource.objects.exists()


@pytest.mark.parametrize("field", RIDE_METRICS)
@pytest.mark.parametrize("value", [None, Decimal("0"), Decimal("1.2300"), Decimal("99999999999999999.999")])
@pytest.mark.django_db
def test_manual_and_fit_preserve_nullable_and_exact_millisecond_metrics(field, value, rides):
    ride = create_manual_ride(rides.owner, started_at=instant(), **{field: value})
    assert getattr(ride, field) == value
    ride, source = imported(rides.owner, **{field: value})
    assert getattr(ride, field) == getattr(source, field) == value


@pytest.mark.parametrize("model", [Ride, ActivitySource])
@pytest.mark.parametrize("field", RIDE_METRICS)
@pytest.mark.parametrize("value", [Decimal("-1"), Decimal("NaN")])
@pytest.mark.django_db
def test_real_sql_metric_constraints_reject_negative_and_nan(model, field, value, rides):
    ride, source = imported(rides.owner)
    obj = ride if model is Ride else source
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'UPDATE "{model._meta.db_table}" SET "{field}" = %s WHERE id = %s', [value, obj.pk])
    assert error.value.__cause__.diag.constraint_name == f"garage_{model.__name__.lower()}_{field}_valid"


@pytest.mark.parametrize("values", [{"owner": 2}, {"id": uuid.uuid4()}, {"field_provenance": {}},
                                     {"manual_overrides": {}}, {"gps": [[1, 2]]}, {"heart_rate": 100}])
@pytest.mark.django_db
def test_closed_manual_whitelist_rejects_forgery_and_personal_payloads(values, rides):
    with pytest.raises(ValidationError):
        create_manual_ride(rides.owner, started_at=instant(), **values)
    assert not Ride.objects.exists()


@pytest.mark.parametrize("values", [{"bike": uuid.uuid4()}, {"gps": [[1, 2]]}, {"serial_number": "SECRET"},
                                     {"notes": "Not a FIT observation"}, {"heart_rate": 100}, {"owner": 2}])
@pytest.mark.django_db
def test_fit_whitelist_rejects_bike_and_raw_personal_fields(values, rides):
    with pytest.raises(ValidationError):
        imported(rides.owner, **values)
    assert not Ride.objects.exists()


@pytest.mark.parametrize("start", [None, date(2026, 1, 1), datetime(2026, 1, 1), "2026-01-01T00:00:00Z"])
@pytest.mark.django_db
def test_new_rides_require_typed_aware_start(start, rides):
    with pytest.raises(ValidationError):
        create_manual_ride(rides.owner, started_at=start)
    with pytest.raises(ValidationError):
        imported(rides.owner, started_at=start)
    assert not Ride.objects.exists()


@pytest.mark.django_db
def test_aware_offset_normalizes_utc_without_inferring_bike_or_timer(rides):
    ride, _ = imported(rides.owner, started_at=datetime(2026, 1, 1, 2, tzinfo=datetime_timezone(timedelta(hours=2))), timer_time_s="10")
    assert ride.started_at == instant() and ride.bike is None and ride.moving_time_s is None


@pytest.mark.parametrize("field,value", [("file_hash", "A" * 64), ("file_hash", "abc"), ("file_hash", None),
                                          ("session_index", -1), ("session_index", True), ("session_index", "0"),
                                          ("parser_version", "/private/path"), ("parser_version", None), ("reactivate", "true")])
@pytest.mark.django_db
def test_source_identity_input_validation_is_coherent_and_atomic(field, value, rides):
    arguments = {"file_hash": "a" * 64, "session_index": 0, "parser_version": "fixture-1",
                 "observations": {"started_at": instant()}, field: value}
    with pytest.raises(ValidationError):
        import_fit_session(rides.owner, **arguments)
    assert not Ride.objects.exists() and not ActivitySource.objects.exists()


@pytest.mark.django_db
def test_identity_cannot_move_to_different_owned_or_foreign_ride(rides):
    ride, source = imported(rides.owner, distance_m="100")
    own = create_manual_ride(rides.owner, started_at=instant(2))
    foreign = create_manual_ride(rides.other, started_at=instant(2))
    with pytest.raises(ValidationError) as error:
        imported(rides.owner, ride_id=own.pk, distance_m="200")
    assert error.value.error_dict["ride_id"][0].code == "source_ride_immutable"
    with pytest.raises(InventoryNotFound):
        imported(rides.owner, ride_id=foreign.pk)
    source.refresh_from_db()
    assert source.ride_id == ride.pk and source.distance_m == Decimal("100")


@pytest.mark.django_db
def test_foreign_bike_and_run_forged_instances_cannot_be_linked(rides):
    rides.foreign_bike.owner = rides.owner
    with pytest.raises(ValidationError):
        create_manual_ride(rides.owner, started_at=instant(), bike=rides.foreign_bike)
    foreign_run = create_import_run(rides.other)
    with pytest.raises(InventoryNotFound):
        import_fit_session(rides.owner, file_hash="a" * 64, session_index=0, parser_version="fixture-1",
                           observations={"started_at": instant()}, import_run_id=foreign_run.pk)
    assert not Ride.objects.exists()


@pytest.mark.parametrize("actor_kind", ["anonymous", "inactive", "unknown"])
@pytest.mark.django_db
def test_all_ride_write_paths_reject_untrusted_actors(actor_kind, rides, django_user_model):
    ride, source = imported(rides.owner)
    if actor_kind == "anonymous":
        actor = AnonymousUser()
    elif actor_kind == "inactive":
        actor = rides.owner
        django_user_model.objects.filter(pk=actor.pk).update(is_active=False)
    else:
        actor = django_user_model(username="not-persisted")
    operations = [lambda: create_manual_ride(actor, started_at=instant()), lambda: imported(actor),
                  lambda: correct_ride(actor, ride.pk, name="Forbidden"),
                  lambda: clear_manual_corrections(actor, ride.pk, fields=["name"]),
                  lambda: withdraw_source(actor, source.pk), lambda: delete_ride(actor, ride.pk)]
    for operation in operations:
        with pytest.raises(PermissionDenied):
            operation()
    assert Ride.objects.count() == 1 and ActivitySource.objects.get().withdrawn_at is None


@pytest.mark.parametrize("foreign_id", ["foreign", "missing", "malformed"])
@pytest.mark.django_db
def test_read_update_delete_and_withdraw_scope_hide_other_owners(foreign_id, rides):
    foreign, foreign_source = imported(rides.other)
    ride_id = foreign.pk if foreign_id == "foreign" else uuid.uuid4() if foreign_id == "missing" else "bad"
    source_id = foreign_source.pk if foreign_id == "foreign" else uuid.uuid4() if foreign_id == "missing" else "bad"
    for operation in [lambda: get_inventory(rides.owner, Ride, ride_id),
                      lambda: correct_ride(rides.owner, ride_id, name="Forbidden"),
                      lambda: clear_manual_corrections(rides.owner, ride_id, fields=["name"]),
                      lambda: delete_ride(rides.owner, ride_id), lambda: withdraw_source(rides.owner, source_id)]:
        with pytest.raises(InventoryNotFound):
            operation()
    assert not scoped_inventory(rides.owner, Ride).exists()
    foreign_source.refresh_from_db()
    assert foreign_source.withdrawn_at is None


@pytest.mark.django_db
def test_bike_fk_protects_manual_history_and_ride_deletion_does_not_touch_foreign_data(rides):
    own = create_manual_ride(rides.owner, started_at=instant(), bike=rides.bike)
    own, _ = imported(rides.owner, ride_id=own.pk)
    foreign, foreign_source = imported(rides.other)
    with pytest.raises(ProtectedError):
        rides.bike.delete()
    delete_ride(rides.owner, own.pk)
    assert not Ride.objects.filter(pk=own.pk).exists()
    assert Ride.objects.filter(pk=foreign.pk).exists() and ActivitySource.objects.filter(pk=foreign_source.pk).exists()


@pytest.mark.django_db
def test_model_validation_rejects_owner_source_retag_and_malformed_json(rides):
    ride, source = imported(rides.owner)
    ride.manual_overrides = {"gps": []}
    with pytest.raises(ValidationError):
        ride.full_clean()
    ride.manual_overrides = {"distance_m": 1.2}
    with pytest.raises(ValidationError):
        ride.full_clean()
    ride.manual_overrides = {}
    ride.field_provenance = {"distance_m": {"token": "secret"}}
    with pytest.raises(ValidationError):
        ride.full_clean()
    source.owner = rides.other
    with pytest.raises(ValidationError):
        source.full_clean()
    source.owner = rides.owner
    source.ride = create_manual_ride(rides.owner, started_at=instant())
    with pytest.raises(ValidationError):
        source.full_clean()


@pytest.mark.parametrize("changes,constraint", [({"source_kind": "garmin"}, ("garage_activitysource_external_identity", "garage_activitysource_kind_valid")),
                                                # garage-030: a Strava row needs its activity id; a FIT row has none.
                                                ({"source_kind": "strava"}, "garage_activitysource_external_identity"),
                                                ({"external_id": 5}, "garage_activitysource_external_identity"),
                                                ({"gear_id": "b1"}, "garage_activitysource_external_identity"),
                                                ({"file_hash": "A" * 64}, "garage_activitysource_hash_valid"),
                                                ({"parser_version": "file/path"}, "garage_activitysource_parser_valid")])
@pytest.mark.django_db
def test_source_sql_constraints_are_real(changes, constraint, rides):
    _, source = imported(rides.owner)
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            ActivitySource.objects.filter(pk=source.pk).update(**changes)
    # PostgreSQL reports the first violated CHECK by name; an unknown kind breaks both kind CHECKs.
    assert error.value.__cause__.diag.constraint_name in (constraint if isinstance(constraint, tuple) else (constraint,))


@pytest.mark.django_db
def test_source_database_identity_and_uuid_uniqueness(rides):
    ride, source = imported(rides.owner)
    fields = dict(owner=rides.owner, ride=ride, file_hash=source.file_hash, session_index=0, parser_version="fixture-1", started_at=instant())
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            ActivitySource.objects.create(**fields)
    assert error.value.__cause__.diag.constraint_name == "garage_activitysource_identity_unique"
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Ride.objects.create(id=ride.pk, owner=rides.owner, started_at=instant())


@pytest.mark.django_db
def test_unexpected_integrity_error_is_not_hidden_and_rolls_back(monkeypatch, rides):
    original = ActivitySource.save
    failure = IntegrityError("synthetic unexpected constraint")
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(ActivitySource, "save", fail)
    with pytest.raises(IntegrityError) as error:
        imported(rides.owner)
    assert error.value is failure and not Ride.objects.exists() and not connection.needs_rollback
    monkeypatch.setattr(ActivitySource, "save", original)
    assert imported(rides.owner)[0].has_known_start


@pytest.mark.django_db(transaction=True)
def test_two_real_connections_import_same_identity_once(rides):
    barrier = Barrier(2)
    def operation():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return imported(rides.owner, distance_m="100")[0].pk
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(operation), pool.submit(operation)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0] == results[1] and Ride.objects.count() == ActivitySource.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_manual_correction_and_fit_reimport_preserve_manual_authority(rides):
    ride, source = imported(rides.owner, distance_m="100")
    barrier = Barrier(2)
    def operation(correction):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return correct_ride(rides.owner, ride.pk, distance_m=None) if correction else imported(rides.owner, distance_m="200")[0]
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(operation, correction) for correction in (True, False)]
        [future.result(timeout=20) for future in futures]
    ride.refresh_from_db()
    source.refresh_from_db()
    assert ride.distance_m is None and ride.manual_overrides["distance_m"] is None and source.distance_m == Decimal("200")


@pytest.mark.django_db
def test_incomplete_withdrawn_ride_can_clear_notes_without_fabricating_start(rides):
    ride, source = imported(rides.owner)
    correct_ride(rides.owner, ride.pk, notes="Own notes")
    withdraw_source(rides.owner, source.pk)
    ride = clear_manual_corrections(rides.owner, ride.pk, fields=["notes"])
    assert ride.started_at is None and ride.notes == "" and not ride.has_known_start


@pytest.mark.parametrize("fields", [[[]], [{}], "notes", {"notes": True}, [1]])
@pytest.mark.django_db
def test_clear_corrections_rejects_structurally_invalid_fields(fields, rides):
    ride = create_manual_ride(rides.owner, started_at=instant(), notes="Preserve")
    with pytest.raises(ValidationError):
        clear_manual_corrections(rides.owner, ride.pk, fields=fields)
    ride.refresh_from_db()
    assert ride.notes == "Preserve"


@pytest.mark.django_db
def test_source_start_is_required_even_if_source_is_withdrawn(rides):
    _, source = imported(rides.owner)
    withdraw_source(rides.owner, source.pk)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ActivitySource.objects.filter(pk=source.pk).update(started_at=None)


@pytest.mark.django_db
def test_provenance_cannot_reference_foreign_or_other_ride_source(rides):
    ride = create_manual_ride(rides.owner, started_at=instant())
    _, own_source = imported(rides.owner)
    _, foreign_source = imported(rides.other)
    for source in (own_source, foreign_source):
        ride.field_provenance = {"distance_m": {"kind": "fit", "source_id": str(source.pk),
                                                 "updated_at": source.observations_updated_at.isoformat()}}
        with pytest.raises(ValidationError):
            ride.full_clean()
