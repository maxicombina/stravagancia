import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import ActivitySource, ImportRun, Ride
from .services.rides import advance_import_run, create_import_run, import_fit_session
from .tests_usage_materialization import instant, usage


@pytest.mark.django_db
def test_bound_manifest_is_minimal_persistent_sorted_and_total_is_selection_length(usage):
    run = create_import_run(usage.owner, file_hash="a" * 64, session_indices=[0, 2, 99])
    run.refresh_from_db()
    assert run.file_hash == "a" * 64 and run.session_indices == [0, 2, 99] and run.total == 3
    advance_import_run(usage.owner, run.pk, state="running", processed=1, cursor=1)
    run = advance_import_run(usage.owner, run.pk, state="paused")
    assert run.session_indices[run.cursor] == 2
    assert set(run.errors) == set() and run.source_kind == "fit"


@pytest.mark.django_db
def test_generic_runs_remain_compatible_without_file_manifest(usage):
    run = create_import_run(usage.owner, total=5)
    assert run.file_hash == "" and run.session_indices == [] and run.total == 5


@pytest.mark.parametrize("file_hash,indices,total", [
    ("a" * 64, [], None), ("", [0], None), (None, [], None), ("A" * 64, [0], None),
    ("a" * 64, [True], None), ("a" * 64, [1.0], None), ("a" * 64, ["1"], None),
    ("a" * 64, [2, 0], None), ("a" * 64, [0, 0], None), ("a" * 64, [-1], None),
    ("a" * 64, [100], None), ("a" * 64, list(range(101)), None), ("a" * 64, {"path": "secret"}, None),
    ("a" * 64, [0, 2], 3), ("a" * 64, [0], True),
])
@pytest.mark.django_db
def test_manifest_strictly_rejects_personal_unordered_duplicate_out_of_bounds_and_wrong_totals(file_hash, indices, total, usage):
    with pytest.raises(ValidationError):
        create_import_run(usage.owner, file_hash=file_hash, session_indices=indices, total=total)
    assert not ImportRun.objects.exists()


@pytest.mark.django_db
def test_manifest_is_immutable_and_advance_cannot_change_bound_total(usage):
    run = create_import_run(usage.owner, file_hash="a" * 64, session_indices=[0, 2])
    for field, value in [("file_hash", "b" * 64), ("session_indices", [0, 1])]:
        setattr(run, field, value)
        with pytest.raises(ValidationError):
            run.full_clean()
        run.refresh_from_db()
    with pytest.raises(ValidationError):
        advance_import_run(usage.owner, run.pk, total=3)
    run.refresh_from_db()
    assert run.total == 2 and run.session_indices == [0, 2] and run.state == "pending"


@pytest.mark.parametrize("hash,index", [("b" * 64, 0), ("a" * 64, 1)])
@pytest.mark.django_db
def test_source_cannot_associate_wrong_hash_or_unselected_session_even_for_own_run(hash, index, usage):
    run = create_import_run(usage.owner, file_hash="a" * 64, session_indices=[0, 2])
    with pytest.raises(ValidationError) as error:
        import_fit_session(usage.owner, file_hash=hash, session_index=index, parser_version="fixture-1",
                           observations={"started_at": instant()}, import_run_id=run.pk)
    assert error.value.error_dict["import_run_id"][0].code == "manifest_mismatch"
    assert not Ride.objects.exists() and not ActivitySource.objects.exists()


@pytest.mark.django_db
def test_source_model_rechecks_bound_manifest_and_matching_session_succeeds(usage):
    run = create_import_run(usage.owner, file_hash="a" * 64, session_indices=[0, 2])
    ride, source = import_fit_session(usage.owner, file_hash="a" * 64, session_index=2, parser_version="fixture-1",
                                     observations={"started_at": instant()}, import_run_id=run.pk)
    assert source.import_run_id == run.pk
    other_run = create_import_run(usage.owner, file_hash="b" * 64, session_indices=[2])
    source.import_run = other_run
    with pytest.raises(ValidationError) as error:
        source.full_clean()
    assert error.value.error_dict["import_run"][0].code == "manifest_mismatch"


@pytest.mark.parametrize("changes", [{"file_hash": "a" * 64}, {"session_indices": [0]},
                                      {"file_hash": "a" * 64, "session_indices": [0], "total": 2},
                                      {"file_hash": "a" * 64, "session_indices": [0], "total": None}])
@pytest.mark.django_db
def test_manifest_pair_and_total_constraint_is_real_sql(changes, usage):
    run = create_import_run(usage.owner)
    with pytest.raises(IntegrityError) as error:
        with transaction.atomic():
            ImportRun.objects.filter(pk=run.pk).update(**changes)
    assert error.value.__cause__.diag.constraint_name == "garage_importrun_manifest_pair"
