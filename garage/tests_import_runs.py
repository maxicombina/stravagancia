from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone as datetime_timezone
from threading import Barrier
import uuid

import pytest
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction

from .models import ActivitySource, ImportRun, Ride
from .services.ownership import InventoryNotFound, get_inventory, scoped_inventory
from .services.rides import advance_import_run, create_import_run, delete_import_run, import_fit_session


def instant(day=1):
    return datetime(2026, 1, day, tzinfo=datetime_timezone.utc)


@pytest.fixture
def actors(db, django_user_model):
    return [django_user_model.objects.create_user(username=name) for name in ("run-owner", "run-other")]


@pytest.mark.django_db
def test_resumable_run_preserves_checkpoint_and_bounded_error_codes(actors):
    owner = actors[0]
    run = create_import_run(owner, requested_from=instant(), requested_to=instant(3), total=3)
    assert run.state == "pending" and run.cursor == run.processed == 0
    run = advance_import_run(owner, run.pk, state="running", processed=2, cursor=1,
                             errors=[{"code": "invalid_session", "session_index": 0}])
    run = advance_import_run(owner, run.pk, state="paused", cursor=2)
    run = advance_import_run(owner, run.pk, state="running")
    assert run.cursor == run.processed == 2 and run.errors == [{"code": "invalid_session", "session_index": 0}]
    run = advance_import_run(owner, run.pk, state="completed", processed=3, cursor=3)
    assert run.state == "completed" and run.processed == run.total == run.cursor == 3


@pytest.mark.django_db
def test_unknown_total_remains_unknown_until_reported_and_failed_run_can_resume(actors):
    run = create_import_run(actors[0])
    run = advance_import_run(actors[0], run.pk, state="running", processed=1, cursor=1)
    assert run.total is None
    run = advance_import_run(actors[0], run.pk, state="failed", errors=[{"code": "invalid_file", "session_index": None}])
    run = advance_import_run(actors[0], run.pk, state="running", total=2)
    run = advance_import_run(actors[0], run.pk, state="completed", processed=2, cursor=2)
    assert run.total == 2 and run.errors[0]["code"] == "invalid_file"


@pytest.mark.parametrize("changes", [{"processed": 0}, {"cursor": 0}, {"total": 0}, {"cursor": 2},
                                      {"processed": 3}, {"state": "completed"}, {"state": []}, {"state": {}},
                                      {"processed": True}, {"cursor": "path"}, {"total": 1.0}, {"state": "unknown"}])
@pytest.mark.django_db
def test_invalid_progress_or_state_rolls_back_entire_update(changes, actors):
    run = create_import_run(actors[0], total=2)
    advance_import_run(actors[0], run.pk, state="running", processed=1, cursor=1)
    with pytest.raises(ValidationError):
        advance_import_run(actors[0], run.pk, **changes)
    run.refresh_from_db()
    assert run.state == "running" and run.processed == run.cursor == 1 and run.total == 2


@pytest.mark.parametrize("terminal", ["completed", "cancelled"])
@pytest.mark.parametrize("changes", [{"state": "running"}, {"processed": 1, "cursor": 1}, {"total": 1},
                                      {"errors": [{"code": "conflict", "session_index": None}]}])
@pytest.mark.django_db
def test_terminal_runs_are_immutable(terminal, changes, actors):
    run = create_import_run(actors[0], total=0)
    if terminal == "completed":
        advance_import_run(actors[0], run.pk, state="running")
    advance_import_run(actors[0], run.pk, state=terminal)
    with pytest.raises(ValidationError):
        advance_import_run(actors[0], run.pk, **changes)
    run.refresh_from_db()
    assert run.state == terminal and run.processed == run.cursor == run.total == 0 and run.errors == []


@pytest.mark.parametrize("errors", [[{"message": "/private/path", "code": "invalid_file", "session_index": 0}],
                                     [{"code": "token=secret", "session_index": 0}],
                                     [{"code": "invalid_file", "session_index": -1}],
                                     [{"code": "invalid_file", "session_index": True}],
                                     [{"code": "invalid_file", "session_index": 2147483648}],
                                     [{"code": [], "session_index": None}],
                                     [{"code": "conflict", "session_index": None}] * 21, {"path": "secret"}, "secret"])
@pytest.mark.django_db
def test_error_payload_is_closed_bounded_and_contains_no_paths_tokens_or_device_data(errors, actors):
    run = create_import_run(actors[0])
    with pytest.raises(ValidationError):
        advance_import_run(actors[0], run.pk, errors=errors)
    run.refresh_from_db()
    assert run.errors == [] and not connection.needs_rollback


@pytest.mark.parametrize("field,value", [("requested_from", datetime(2026, 1, 1)), ("requested_to", date(2026, 1, 1)),
                                         ("requested_to", "2026-01-02T00:00:00Z"), ("total", -1),
                                         ("total", True), ("total", 2147483648)])
@pytest.mark.django_db
def test_create_run_rejects_invalid_intervals_and_counter_types(field, value, actors):
    with pytest.raises(ValidationError):
        create_import_run(actors[0], **{field: value})
    assert not ImportRun.objects.exists()


@pytest.mark.django_db
def test_run_requested_interval_is_positive_and_completion_requires_full_checkpoint(actors):
    with pytest.raises(ValidationError):
        create_import_run(actors[0], requested_from=instant(2), requested_to=instant())
    run = create_import_run(actors[0])
    advance_import_run(actors[0], run.pk, state="running", processed=2, cursor=1)
    with pytest.raises(ValidationError):
        advance_import_run(actors[0], run.pk, state="completed")
    assert advance_import_run(actors[0], run.pk, state="completed", cursor=2).state == "completed"


@pytest.mark.parametrize("actor_kind", ["anonymous", "inactive", "unknown"])
@pytest.mark.django_db
def test_import_jobs_require_authenticated_active_persisted_actor(actor_kind, actors, django_user_model):
    run = create_import_run(actors[0])
    if actor_kind == "anonymous":
        actor = AnonymousUser()
    elif actor_kind == "unknown":
        actor = django_user_model(username="unsaved")
    else:
        actor = actors[0]
        django_user_model.objects.filter(pk=actor.pk).update(is_active=False)
    for operation in [lambda: create_import_run(actor), lambda: advance_import_run(actor, run.pk, state="running"),
                      lambda: delete_import_run(actor, run.pk), lambda: get_inventory(actor, ImportRun, run.pk)]:
        with pytest.raises(PermissionDenied):
            operation()
    assert ImportRun.objects.get().state == "pending"


@pytest.mark.parametrize("kind", ["foreign", "missing", "malformed"])
@pytest.mark.django_db
def test_import_run_get_advance_delete_are_actor_scoped(kind, actors):
    foreign = create_import_run(actors[1])
    run_id = foreign.pk if kind == "foreign" else uuid.uuid4() if kind == "missing" else "bad"
    for operation in [lambda: get_inventory(actors[0], ImportRun, run_id),
                      lambda: advance_import_run(actors[0], run_id, state="running"),
                      lambda: delete_import_run(actors[0], run_id)]:
        with pytest.raises(InventoryNotFound):
            operation()
    assert not scoped_inventory(actors[0], ImportRun).exists() and ImportRun.objects.get().state == "pending"


@pytest.mark.django_db
def test_deleting_import_metadata_keeps_source_and_own_ride(actors):
    own = create_import_run(actors[0])
    foreign = create_import_run(actors[1])
    ride, source = import_fit_session(actors[0], file_hash="a" * 64, session_index=0, parser_version="fixture-1",
                                    observations={"started_at": instant(), "distance_m": "123"}, import_run_id=own.pk)
    delete_import_run(actors[0], own.pk)
    source.refresh_from_db()
    assert source.import_run_id is None and Ride.objects.get(pk=ride.pk).distance_m == 123
    assert ImportRun.objects.filter(pk=foreign.pk).exists()


@pytest.mark.parametrize("changes,constraint", [
    # garage-030 widened the kind CHECK; a Strava job keeps no manifest nor total.
    ({"source_kind": "garmin"}, "garage_importrun_source_valid"), ({"source_kind": "strava", "total": 3}, "garage_importrun_strava_pages"),
    ({"state": "unknown"}, "garage_importrun_state_valid"),
    ({"total": 0, "processed": 1}, "garage_importrun_progress_bounded"),
    ({"cursor": 1}, "garage_importrun_cursor_bounded"),
    ({"state": "completed", "processed": 1, "cursor": 0}, "garage_importrun_completed_cursor"),
    ({"state": "completed", "processed": 1, "cursor": 1, "total": 2}, "garage_importrun_completed_progress"),
    ({"requested_from": instant(2), "requested_to": instant()}, "garage_importrun_interval_valid"),
])
@pytest.mark.django_db
def test_real_sql_import_constraints(changes, constraint, actors):
    run = create_import_run(actors[0])
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            ImportRun.objects.filter(pk=run.pk).update(**changes)
    assert error.value.__cause__.diag.constraint_name == constraint


@pytest.mark.parametrize("field", ["processed", "cursor", "total"])
@pytest.mark.django_db
def test_database_rejects_negative_progress(field, actors):
    run = create_import_run(actors[0])
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ImportRun.objects.filter(pk=run.pk).update(**{field: -1})


@pytest.mark.django_db
def test_model_validation_rejects_owner_mutation_and_private_error_metadata(actors):
    run = create_import_run(actors[0])
    run.owner = actors[1]
    with pytest.raises(ValidationError):
        run.full_clean()
    run.owner = actors[0]
    run.errors = [{"code": "invalid_file", "session_index": None, "token": "private"}]
    with pytest.raises(ValidationError):
        run.full_clean()


@pytest.mark.django_db(transaction=True)
def test_real_connections_cannot_regress_resume_checkpoint(actors):
    run = create_import_run(actors[0], total=2)
    advance_import_run(actors[0], run.pk, state="running")
    barrier = Barrier(2)
    def advance(amount):
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            try:
                return advance_import_run(actors[0], run.pk, processed=amount, cursor=amount).processed
            except ValidationError as error:
                assert error.error_dict["processed"][0].code == "invalid_progress"
                return "regression_rejected"
        finally:
            close_old_connections()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(advance, amount) for amount in (1, 2)]
        results = [future.result(timeout=20) for future in futures]
    run.refresh_from_db()
    assert run.processed == run.cursor == 2 and 2 in results
    assert results[0] in (1, "regression_rejected")
