"""Strava as a Garage source (garage-030): mapping, linking, precedence, gear and moves."""
from datetime import timedelta
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import ActivitySource, Bike, Category, Item, ItemUsage, Ride, StravaAccount, StravaEvent, StravaGear
from .services.home import pending_rides
from .services.import_history import history_queryset
from .services.installations import create_installation
from .services.ownership import InventoryNotFound, _lock_owner, create_inventory
from .services.ride_review import review_state
from .services.rides import correct_ride, create_manual_ride, import_fit_session, withdraw_source
from .services.strava_sources import (dismiss_duplicate, identity_hash, link_gear, merge_candidates, merge_source,
                                      parse_activity, rebuild_rides_locked, refresh_gear, remove_strava_data,
                                      separate_source, store_activity)
from .services.strava_sync import ENV_SCOPES
from .services.usage_profiles import create_profile_history, resolve_ride_usage
from .sports import CYCLING_KEYS, STRAVA_CYCLING, profile_covers
from .tests_strava_client import ATHLETE, activity_text, at


@pytest.fixture
def g(db, django_user_model):
    owner = django_user_model.objects.create_user(username="source-owner")
    other = django_user_model.objects.create_user(username="source-other")
    account = StravaAccount.objects.create(owner=owner, athlete_id=ATHLETE, scopes=ENV_SCOPES)
    category = create_inventory(owner, Category, name="Equipación")
    return SimpleNamespace(owner=owner, other=other, account=account, category=category,
                           gravel=create_inventory(owner, Bike, name="Gravel"), road=create_inventory(owner, Bike, name="Carretera"))


def store(g, activity_id, *, owner=None, account=None, **values):
    data = json.loads(activity_text(activity_id, **values), parse_float=Decimal)
    with transaction.atomic():
        locked = _lock_owner(owner or g.owner)
        touched = set()
        outcome = store_activity(locked, account or g.account, data, touched=touched)
        rebuild_rides_locked(locked, touched)
    return outcome


def fit(g, start, *, distance=Decimal("30000"), file_hash="a" * 64, ride_id=None):
    return import_fit_session(g.owner, file_hash=file_hash, session_index=0, parser_version="fixture-1", ride_id=ride_id,
                              observations={"started_at": start, "sport_type": "cycling", "distance_m": distance,
                                            "timer_time_s": Decimal("3700.5"), "elapsed_time_s": Decimal("4100")})


def strava_source(activity_id):
    return ActivitySource.objects.get(source_kind="strava", external_id=activity_id)


def item(g, name):
    return create_inventory(g.owner, Item, name=name, category=g.category)


# Mapping -------------------------------------------------------------------

@pytest.mark.parametrize("sport,key", sorted(STRAVA_CYCLING.items()))
def test_cycling_sports_are_canonical(sport, key):
    observation = parse_activity(json.loads(activity_text(5, start=at(), sport=sport), parse_float=Decimal))
    assert observation.sport_type == key and key in CYCLING_KEYS


def test_observation_is_minimal_exact_and_honest():
    data = json.loads(activity_text(5, start=at(), distance="30123.4", gear="b77", extra=', "map": {"polyline": "x"}, '
                                    '"average_heartrate": 150.1'), parse_float=Decimal)
    observation = parse_activity(data)
    assert observation.values == {"started_at": at(), "name": "Vuelta", "sport_type": "cycling", "distance_m": Decimal("30123.400"),
                                  "moving_time_s": Decimal("3600.000"), "timer_time_s": None, "elapsed_time_s": Decimal("4000.000"),
                                  "elevation_gain_m": Decimal("12.300"), "average_power_w": None, "max_power_w": None,
                                  "weighted_power_w": None, "energy_kj": None}
    assert observation.gear_id == "b77" and observation.athlete_id == ATHLETE
    # A float, a negative or an over-precise number is unknown, never rounded.
    for value in (30000.5, "-1", "1.0001"):
        raw = dict(data, distance=value if isinstance(value, float) else Decimal(value))
        assert parse_activity(raw).values["distance_m"] is None
    legacy = {key: value for key, value in data.items() if key != "sport_type"}
    assert parse_activity(dict(legacy, type="VirtualRide")).sport_type == "virtual_ride"
    for broken in ({**data, "id": "5"}, {**data, "start_date": "2026-03-01T10:00:00"}, {**data, "start_date": None}, []):
        with pytest.raises(ValueError):
            parse_activity(broken)


def test_identity_hash_keeps_the_existing_hash_contract():
    value = identity_hash(ATHLETE, 5)
    assert len(value) == 64 and value == identity_hash(ATHLETE, 5) != identity_hash(ATHLETE + 1, 5)


@pytest.mark.django_db
def test_other_sports_are_skipped_and_counted(g):
    assert store(g, 1, start=at(), sport="Run").kind == "skipped_sport"
    assert not ActivitySource.objects.exists() and not Ride.objects.exists()
    assert store(g, 2, start=at(), sport="GravelRide", gear="b9").kind == "imported"
    source = strava_source(2)
    assert (source.session_index, source.parser_version, source.file_hash) == (0, "strava-api-v3", identity_hash(ATHLETE, 2))
    assert StravaGear.objects.get(owner=g.owner).gear_id == "b9"
    # The same activity changed to a non-cycling sport on Strava: its data goes (no stale Strava data).
    assert store(g, 2, start=at(), sport="Walk").kind == "removed"
    assert not ActivitySource.objects.exists() and not Ride.objects.exists()


@pytest.mark.django_db
def test_foreign_athlete_payload_is_rejected(g):
    with pytest.raises(ValueError):
        store(g, 3, start=at(), athlete=ATHLETE + 1)
    assert not Ride.objects.exists()


@pytest.mark.django_db
def test_snapshot_updates_unchanged_and_withdrawn(g):
    assert store(g, 4, start=at(), name="Uno").kind == "imported"
    stamp = strava_source(4).observations_updated_at
    assert store(g, 4, start=at(), name="Uno").kind == "unchanged" and strava_source(4).observations_updated_at == stamp
    assert store(g, 4, start=at(), name="Dos").kind == "updated"
    ride = Ride.objects.get()
    assert ride.name == "Dos" and ride.field_provenance["name"]["kind"] == "strava"
    withdraw_source(g.owner, strava_source(4).pk)
    assert store(g, 4, start=at(), name="Tres").kind == "skipped_withdrawn"
    assert strava_source(4).name == "Dos" and strava_source(4).withdrawn_at is not None


@pytest.mark.django_db
def test_database_identity_for_strava_rows(g):
    store(g, 5, start=at())
    source = strava_source(5)
    with pytest.raises(IntegrityError) as error, transaction.atomic():
        ActivitySource.objects.create(owner=g.owner, ride=source.ride, source_kind="strava", external_id=5, file_hash="b" * 64,
                                      session_index=0, parser_version="strava-api-v3", started_at=at())
    assert error.value.__cause__.diag.constraint_name == "garage_activitysource_strava_unique"
    for changes in ({"session_index": 1}, {"external_id": None}, {"source_kind": "fit"}):
        with pytest.raises(IntegrityError), transaction.atomic():
            ActivitySource.objects.filter(pk=source.pk).update(**changes)
    source.external_id = 6
    with pytest.raises(ValidationError):
        source.full_clean()


# Profiles by sport family --------------------------------------------------

def test_profile_family_rule():
    assert profile_covers("", "running") and profile_covers("cycling", "gravel_ride") and profile_covers("cycling", "cycling")
    assert profile_covers("gravel_ride", "gravel_ride") and not profile_covers("gravel_ride", "cycling")
    assert not profile_covers("cycling", "running") and not profile_covers("cycling", "") and not profile_covers("virtual_ride", "gravel_ride")


@pytest.mark.django_db
def test_usage_profiles_match_by_family(g):
    helmet, shoes, roller, lights = (item(g, name) for name in ("Casco", "Zapatillas gravel", "Rodillo", "Luces"))
    for name, sport, items in (("Ciclismo", "cycling", [helmet]), ("Gravel", "gravel_ride", [shoes]), ("Rodillo", "virtual_ride", [roller]),
                               ("Todo", "", [lights])):
        create_profile_history(g.owner, items=items, started_at=at(1) - timedelta(days=30), name=name, sport_type=sport)
    expected = {"gravel_ride": {helmet, shoes, lights}, "virtual_ride": {helmet, roller, lights}, "cycling": {helmet, lights},
                "mountain_bike_ride": {helmet, lights}, "running": {lights}}
    for day, (sport, items) in enumerate(expected.items(), 1):
        ride = create_manual_ride(g.owner, started_at=at(day), sport_type=sport)
        assert resolve_ride_usage(g.owner, ride.pk).item_ids == {obj.pk for obj in items}, sport
        assert set(ItemUsage.objects.filter(ride=ride).values_list("item_id", flat=True)) == {obj.pk for obj in items}
        state = review_state(g.owner, ride.pk)
        assert {row.item.pk for row in state.candidates} == {obj.pk for obj in items}, sport


# Linking -------------------------------------------------------------------

@pytest.mark.django_db
def test_strava_joins_the_single_matching_fit_ride(g):
    ride, fit_source = fit(g, at(hour=10))
    # 89 s later and 1.9 % longer: same ride.
    assert store(g, 10, start=at(hour=10, minute=1, second=29), distance="30570.0", sport="GravelRide").ride_id == ride.pk
    ride.refresh_from_db()
    source = strava_source(10)
    assert source.ride_id == ride.pk and not source.possible_duplicate
    assert ride.distance_m == Decimal("30000.000") and ride.field_provenance["distance_m"]["kind"] == "fit"
    assert ride.started_at == at(hour=10) and ride.field_provenance["started_at"]["source_id"] == str(fit_source.pk)
    # Strava fills what FIT lacks and its specific sport refines FIT's generic `cycling`.
    assert (ride.name, ride.field_provenance["name"]["kind"]) == ("Vuelta", "strava")
    assert ride.moving_time_s == Decimal("3600.000") and ride.field_provenance["moving_time_s"]["kind"] == "strava"
    assert ride.timer_time_s == Decimal("3700.500") and ride.field_provenance["timer_time_s"]["kind"] == "fit"
    assert ride.elapsed_time_s == Decimal("4100.000") and ride.field_provenance["elapsed_time_s"]["kind"] == "fit"
    assert (ride.sport_type, ride.field_provenance["sport_type"]["kind"]) == ("gravel_ride", "strava")
    assert Ride.objects.count() == 1


@pytest.mark.django_db
def test_a_generic_strava_sport_does_not_beat_fit(g):
    ride, fit_source = fit(g, at())
    store(g, 11, start=at(), sport="Ride")
    ride.refresh_from_db()
    assert ride.sport_type == "cycling" and ride.field_provenance["sport_type"]["source_id"] == str(fit_source.pk)


@pytest.mark.django_db
@pytest.mark.parametrize("delta,distance,joins", [(91, "30000.0", False), (0, "30700.0", False), (-90, "29400.0", True),
                                                  (30, "null", True)])
def test_matching_tolerances(g, delta, distance, joins):
    ride, _ = fit(g, at(hour=12))
    store(g, 12, start=at(hour=12) + timedelta(seconds=delta), distance=distance)
    assert (strava_source(12).ride_id == ride.pk) is joins
    assert not strava_source(12).possible_duplicate


@pytest.mark.django_db
def test_zero_one_and_two_candidates(g):
    assert store(g, 20, start=at(5)).kind == "imported" and not strava_source(20).possible_duplicate  # zero: new ride
    first, _ = fit(g, at(6), file_hash="1" * 64)
    second, _ = fit(g, at(6) + timedelta(seconds=40), file_hash="2" * 64)
    store(g, 21, start=at(6) + timedelta(seconds=20))
    source = strava_source(21)
    assert source.ride_id not in (first.pk, second.pk) and source.possible_duplicate
    assert {row.ride.pk for row in merge_candidates(g.owner, source.pk) if row.matches} == {first.pk, second.pk}


@pytest.mark.django_db
def test_one_active_strava_source_per_ride(g):
    store(g, 30, start=at(7))
    ride = strava_source(30).ride
    store(g, 31, start=at(7) + timedelta(seconds=5))  # a second Strava id for the same ride: never joined
    second = strava_source(31)
    assert second.ride_id != ride.pk and second.possible_duplicate
    with pytest.raises(ValidationError) as error:
        merge_source(g.owner, second.pk, ride.pk)
    assert error.value.error_dict["ride"][0].code == "class_taken"


@pytest.mark.django_db
def test_manual_ride_is_a_candidate_with_its_own_values(g):
    manual = create_manual_ride(g.owner, started_at=at(8), distance_m=Decimal("50000"), sport_type="")
    store(g, 40, start=at(8) + timedelta(seconds=10), distance="50500.0")
    manual.refresh_from_db()
    assert strava_source(40).ride_id == manual.pk and manual.distance_m == Decimal("50000.000")
    assert manual.field_provenance["distance_m"]["kind"] == "manual" and manual.moving_time_s == Decimal("3600.000")
    other = create_manual_ride(g.owner, started_at=at(9), sport_type="running")
    store(g, 41, start=at(9))
    assert strava_source(41).ride_id != other.pk, "a non-cycling ride is never a candidate"


@pytest.mark.django_db
def test_a_later_fit_joins_only_a_strava_only_ride(g):
    store(g, 50, start=at(10), distance="40000.0", sport="MountainBikeRide")
    ride = strava_source(50).ride
    joined, source = fit(g, at(10) + timedelta(seconds=30), distance=Decimal("40100"))
    assert joined.pk == ride.pk and not source.possible_duplicate
    assert joined.distance_m == Decimal("40100.000") and joined.field_provenance["distance_m"]["kind"] == "fit"
    assert joined.sport_type == "mountain_bike_ride" and joined.field_provenance["sport_type"]["kind"] == "strava"
    # That ride now has FIT and Strava: another FIT of the same moment never joins it (never FIT↔FIT)
    # and is marked as a possible duplicate instead of silently counting twice (garage-030 review).
    again, source = fit(g, at(10) + timedelta(seconds=31), distance=Decimal("40100"), file_hash="9" * 64)
    assert again.pk != ride.pk and source.possible_duplicate
    # Two Strava-only matches: a new ride marked as possible duplicate.
    store(g, 51, start=at(11))
    store(g, 52, start=at(11) + timedelta(seconds=60))
    ambiguous, source = fit(g, at(11) + timedelta(seconds=30), file_hash="8" * 64)
    assert ambiguous.pk not in (strava_source(51).ride_id, strava_source(52).ride_id) and source.possible_duplicate


@pytest.mark.django_db
def test_reimporting_the_fit_after_strava_keeps_precedence(g):
    ride, _ = fit(g, at(12))
    store(g, 60, start=at(12), distance="30500.0")
    again, _ = fit(g, at(12))
    again.refresh_from_db()
    assert again.pk == ride.pk and again.distance_m == Decimal("30000.000") and again.field_provenance["distance_m"]["kind"] == "fit"


@pytest.mark.django_db
def test_manual_corrections_beat_every_source(g):
    store(g, 70, start=at(13), gear="b1")
    ride = strava_source(70).ride
    gear = StravaGear.objects.get(gear_id="b1")
    link_gear(g.owner, gear.pk, g.gravel)
    correct_ride(g.owner, ride.pk, distance_m=Decimal("1.5"), bike=g.road.pk, sport_type="cycling")
    store(g, 70, start=at(13), gear="b1", distance="99999.0", sport="GravelRide")
    ride.refresh_from_db()
    assert (ride.distance_m, ride.bike_id, ride.sport_type) == (Decimal("1.500"), g.road.pk, "cycling")
    assert {ride.field_provenance[field]["kind"] for field in ("distance_m", "bike", "sport_type")} == {"manual"}


# Gear ----------------------------------------------------------------------

@pytest.mark.django_db
def test_gear_link_unlink_and_retire_rebuild_usage(g):
    chain = item(g, "Cadena")
    create_installation(g.owner, item=chain, bike=g.gravel, started_at=at(1) - timedelta(days=60), slot="chain")
    store(g, 80, start=at(14), gear="b1")
    ride = strava_source(80).ride
    assert ride.bike_id is None and ride in pending_rides(g.owner)
    assert not ItemUsage.objects.filter(ride=ride).exists()
    gear = StravaGear.objects.get(gear_id="b1")
    link_gear(g.owner, gear.pk, g.gravel)
    ride.refresh_from_db()
    assert ride.bike_id == g.gravel.pk and ride.field_provenance["bike"] == {
        "kind": "strava", "source_id": str(strava_source(80).pk), "updated_at": strava_source(80).observations_updated_at.isoformat()}
    assert ride not in pending_rides(g.owner)
    assert list(ItemUsage.objects.filter(ride=ride).values_list("item_id", "bike_id")) == [(chain.pk, g.gravel.pk)]
    # Retired on Strava: the link stays (old rides used that bike); its rides are recalculated.
    with transaction.atomic():
        locked, touched = _lock_owner(g.owner), set()
        refresh_gear(locked, [{"id": "b1", "name": "Gravel vieja", "retired": True}], touched)
        rebuild_rides_locked(locked, touched)
    gear.refresh_from_db()
    ride.refresh_from_db()
    assert gear.retired and gear.name == "Gravel vieja" and ride.pk in touched and ride.bike_id == g.gravel.pk
    link_gear(g.owner, gear.pk, None)
    ride.refresh_from_db()
    assert ride.bike_id is None and ride.field_provenance["bike"]["kind"] == "unknown"
    assert not ItemUsage.objects.filter(ride=ride).exists()


@pytest.mark.django_db
def test_gear_is_owner_scoped(g):
    gear = StravaGear.objects.create(owner=g.owner, gear_id="b5")
    foreign_bike = create_inventory(g.other, Bike, name="Ajena")
    with pytest.raises(ValidationError):
        link_gear(g.owner, gear.pk, foreign_bike)
    with pytest.raises(InventoryNotFound):
        link_gear(g.other, gear.pk, None)
    with pytest.raises(ValidationError), transaction.atomic():
        gear.bike = foreign_bike
        gear.full_clean()


@pytest.mark.django_db
def test_manual_bike_beats_the_gear_link(g):
    store(g, 81, start=at(15), gear="b1")
    ride = strava_source(81).ride
    correct_ride(g.owner, ride.pk, bike=g.road.pk)
    link_gear(g.owner, StravaGear.objects.get(gear_id="b1").pk, g.gravel)
    ride.refresh_from_db()
    assert ride.bike_id == g.road.pk and ride.field_provenance["bike"]["kind"] == "manual"


# Separate and join ---------------------------------------------------------

@pytest.mark.django_db
def test_separate_and_join_recalculate_both_rides_and_usage(g):
    helmet = item(g, "Casco")
    create_profile_history(g.owner, items=[helmet], started_at=at(1) - timedelta(days=30), name="Ciclismo", sport_type="cycling")
    ride, fit_source = fit(g, at(16))
    store(g, 90, start=at(16), sport="VirtualRide", name="Rodillo")
    source = strava_source(90)
    ride.refresh_from_db()
    assert ride.sport_type == "virtual_ride" and source.ride_id == ride.pk
    separated = separate_source(g.owner, source.pk)
    ride.refresh_from_db()
    source.refresh_from_db()
    assert source.ride_id == separated.pk != ride.pk
    assert (ride.sport_type, ride.name) == ("cycling", "") and (separated.sport_type, separated.name) == ("virtual_ride", "Rodillo")
    assert all(entry["kind"] in ("fit", "unknown") for entry in ride.field_provenance.values())
    assert set(ItemUsage.objects.filter(item=helmet).values_list("ride_id", flat=True)) == {ride.pk, separated.pk}
    with pytest.raises(ValidationError) as error:
        separate_source(g.owner, source.pk)
    assert error.value.error_dict["source"][0].code == "nothing_to_separate"
    joined = merge_source(g.owner, source.pk, ride.pk)
    assert joined.pk == ride.pk and joined.sport_type == "virtual_ride"
    assert not Ride.objects.filter(pk=separated.pk).exists(), "an emptied automatic ride is deleted"
    assert set(ItemUsage.objects.filter(item=helmet).values_list("ride_id", flat=True)) == {ride.pk}
    with pytest.raises(ValidationError):
        merge_source(g.owner, source.pk, ride.pk)  # same ride
    other, _ = fit(g, at(17), file_hash="7" * 64)
    with pytest.raises(ValidationError) as error:
        merge_source(g.owner, fit_source.pk, other.pk)
    assert error.value.error_dict["ride"][0].code == "class_taken", "never FIT↔FIT"


@pytest.mark.django_db
def test_join_keeps_an_old_ride_with_measurement_corrections(g):
    target = create_manual_ride(g.owner, started_at=at(18))
    store(g, 91, start=at(18) + timedelta(hours=2))
    old = strava_source(91).ride
    correct_ride(g.owner, old.pk, distance_m=Decimal("10"))
    merge_source(g.owner, strava_source(91).pk, target.pk)
    old.refresh_from_db()
    assert old.distance_m == Decimal("10.000") and old.name == ""


@pytest.mark.django_db
def test_moves_are_owner_scoped_and_only_in_the_service(g):
    store(g, 92, start=at(19))
    source = strava_source(92)
    foreign = create_manual_ride(g.other, started_at=at(19))
    for operation in (lambda: merge_source(g.owner, source.pk, foreign.pk), lambda: merge_source(g.other, source.pk, foreign.pk),
                      lambda: separate_source(g.other, source.pk), lambda: dismiss_duplicate(g.other, source.pk)):
        with pytest.raises(InventoryNotFound):
            operation()
    source.ride = create_manual_ride(g.owner, started_at=at(20))
    with pytest.raises(ValidationError):
        source.full_clean()


@pytest.mark.django_db
def test_dismissing_a_duplicate_only_clears_the_mark(g):
    store(g, 93, start=at(21))
    store(g, 94, start=at(21))
    source = strava_source(94)
    assert source.possible_duplicate
    before = source.ride.field_provenance
    dismiss_duplicate(g.owner, source.pk)
    source.refresh_from_db()
    assert not source.possible_duplicate and source.ride.field_provenance == before


# Removing what came from Strava ------------------------------------------------

@pytest.mark.django_db
def test_remove_strava_data(g):
    helmet = item(g, "Casco")
    create_profile_history(g.owner, items=[helmet], started_at=at(1) - timedelta(days=30), name="Todo", sport_type="")
    only, bike_only, measured = (store(g, key, start=at(day), gear="b1").ride_id for key, day in ((100, 22), (101, 23), (102, 24)))
    both, _ = fit(g, at(25))
    store(g, 103, start=at(25), gear="b1")
    correct_ride(g.owner, bike_only, bike=g.road.pk, notes="sólo la bici")
    correct_ride(g.owner, measured, moving_time_s=Decimal("100"))
    link_gear(g.owner, StravaGear.objects.get(gear_id="b1").pk, g.gravel)
    StravaEvent.objects.create(subscription_id=1, athlete_id=ATHLETE, object_type="activity", aspect_type="create", object_id=100,
                               event_time=at())
    foreign_account = StravaAccount.objects.create(owner=g.other, athlete_id=ATHLETE + 1)
    result = remove_strava_data(g.owner)
    assert (result.sources, result.deleted_rides, result.kept_rides, result.gear) == (4, 2, 2, 1)
    assert set(Ride.objects.filter(owner=g.owner).values_list("pk", flat=True)) == {measured, both.pk}
    assert not ActivitySource.objects.filter(source_kind="strava").exists() and not StravaGear.objects.exists()
    assert not StravaAccount.objects.filter(owner=g.owner).exists() and StravaAccount.objects.filter(pk=foreign_account.pk).exists()
    assert not StravaEvent.objects.exists()
    kept = Ride.objects.get(pk=measured)
    assert kept.started_at is None and kept.moving_time_s == Decimal("100.000") and kept.bike_id is None
    both.refresh_from_db()
    assert both.bike_id is None and both.name == "" and all(entry["kind"] != "strava" for entry in both.field_provenance.values())
    assert set(ItemUsage.objects.filter(item=helmet).values_list("ride_id", flat=True)) == {both.pk}


@pytest.mark.django_db
def test_pending_criteria_do_not_change(g):
    """«Por revisar» stays «known start, no bike decided»; the history filter keeps its four metrics."""
    store(g, 110, start=at(26), gear="b1")
    ride = strava_source(110).ride
    assert ride in pending_rides(g.owner)
    link_gear(g.owner, StravaGear.objects.get(gear_id="b1").pk, g.gravel)
    assert ride not in pending_rides(g.owner)
    # Strava has no timer time: unknown, so the history «pendientes o campos desconocidos» still lists it.
    assert ride in history_queryset(g.owner, pending=True)


# Review of phases 1–2 (18 oct) -----------------------------------------------------

@pytest.mark.django_db
def test_a_second_fit_of_the_same_moment_is_marked_not_silently_counted(g):
    ride, first = fit(g, at(27), file_hash="c" * 64)
    # Another session of the same file is not a duplicate of its sibling.
    sibling = import_fit_session(g.owner, file_hash="c" * 64, session_index=1, parser_version="fixture-1",
                                 observations={"started_at": at(27) + timedelta(seconds=30), "sport_type": "cycling",
                                               "distance_m": Decimal("30000")})[1]
    assert not sibling.possible_duplicate and sibling.ride_id != ride.pk
    other, second = fit(g, at(27) + timedelta(seconds=20), file_hash="d" * 64)
    assert other.pk not in (ride.pk, sibling.ride_id) and second.possible_duplicate and not first.possible_duplicate, \
        "never FIT↔FIT, but flagged"
    # Far enough (> 90 s from every session) or a clearly different distance: no mark.
    assert not fit(g, at(27) + timedelta(seconds=121), file_hash="e" * 64)[1].possible_duplicate
    assert not fit(g, at(27), distance=Decimal("40000"), file_hash="f" * 64)[1].possible_duplicate


@pytest.mark.django_db
def test_join_keeps_an_old_ride_with_any_correction_or_exception(g):
    from .services.strava_sources import merge_effects
    from .services.usage_profiles import set_usage_override
    from .models import UsageOverride
    helmet = item(g, "Casco")
    rides = {}
    for key, day in ((120, 1), (121, 2), (122, 3)):
        target = create_manual_ride(g.owner, started_at=at(day, hour=8))
        store(g, key, start=at(day, hour=10))
        rides[key] = (target, strava_source(key).ride)
    correct_ride(g.owner, rides[120][1].pk, notes="Pinchazo en el km 30", name="Con Ana")
    set_usage_override(g.owner, ride=rides[121][1].pk, item=helmet.pk, action="exclude")
    effects = {key: merge_effects(g.owner, strava_source(key).pk) for key in rides}
    assert effects[120].corrections == ("name", "notes") and not effects[120].deletes_ride and effects[120].loses_start
    assert effects[121].overrides == 1 and not effects[121].deletes_ride
    assert effects[122].deletes_ride and effects[122].corrections == () and effects[122].overrides == 0
    for key, (target, _) in rides.items():
        merge_source(g.owner, strava_source(key).pk, target.pk)
    kept = Ride.objects.get(pk=rides[120][1].pk)
    assert (kept.notes, kept.name, kept.started_at) == ("Pinchazo en el km 30", "Con Ana", None), "notes and name are not lost"
    assert UsageOverride.objects.filter(ride_id=rides[121][1].pk).exists(), "a usage exception keeps its ride"
    assert not Ride.objects.filter(pk=rides[122][1].pk).exists(), "an emptied automatic ride is still deleted"
    # The policy-driven removals keep their documented rule: only measurement corrections keep a ride.
    store(g, 123, start=at(4))
    correct_ride(g.owner, strava_source(123).ride_id, notes="sólo notas")
    gone = strava_source(123).ride_id
    remove_strava_data(g.owner)
    assert not Ride.objects.filter(pk=gone).exists()


@pytest.mark.django_db
def test_event_activities_must_name_this_athlete(g):
    data = json.loads(activity_text(130, start=at(5)), parse_float=Decimal)
    del data["athlete"]
    with transaction.atomic():
        locked, touched = _lock_owner(g.owner), set()
        with pytest.raises(ValueError):
            store_activity(locked, g.account, data, touched=touched, require_athlete=True)
        assert store_activity(locked, g.account, data, touched=touched).kind == "imported", "a list page is already scoped"


@pytest.mark.django_db
def test_batch_linking_sees_rides_created_earlier_in_the_same_page(g):
    from .services.strava_sync import _store_rows
    ride, _ = fit(g, at(6))
    rows = [json.loads(activity_text(key, start=at(6) + timedelta(seconds=key - 140)), parse_float=Decimal) for key in (140, 141)]
    rows.append(json.loads(activity_text(142, start=at(7)), parse_float=Decimal))
    rows.append(json.loads(activity_text(143, start=at(7) + timedelta(seconds=10)), parse_float=Decimal))
    with transaction.atomic():
        result = _store_rows(_lock_owner(g.owner), g.account, rows)
    assert result.imported == 4
    assert strava_source(140).ride_id == ride.pk and not strava_source(140).possible_duplicate
    assert strava_source(141).ride_id != ride.pk and strava_source(141).possible_duplicate, "the FIT ride got its Strava source in this page"
    assert strava_source(143).ride_id != strava_source(142).ride_id and strava_source(143).possible_duplicate


@pytest.mark.django_db
def test_a_failed_activity_does_not_corrupt_the_rest_of_its_page(g):
    from unittest.mock import patch
    from .services import strava_sources
    from .services.strava_sync import _store_rows
    rows = [json.loads(activity_text(key, start=at(8, hour=8 + key - 150), gear=f"g{key}"), parse_float=Decimal) for key in (150, 151, 152)]
    original = strava_sources.ActivitySource.save
    def failing(self, *args, **kwargs):
        if self.external_id == 151:
            raise IntegrityError("synthetic")
        return original(self, *args, **kwargs)
    with patch.object(strava_sources.ActivitySource, "save", failing), transaction.atomic():
        result = _store_rows(_lock_owner(g.owner), g.account, rows)
    assert (result.imported, result.invalid) == (2, 1)
    assert set(StravaGear.objects.values_list("gear_id", flat=True)) == {"g150", "g152"}, "the rolled-back gear is not assumed"
    assert Ride.objects.count() == 2
