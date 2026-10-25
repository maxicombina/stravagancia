"""garage-043, independent review (Opus, 25 oct 2026): findings R043-n that fail with the reviewed code.

Synthetic only (the helpers of tests_probikegarage_import): the owner's real dump is
never read here. Each test names its finding in .claude/specs/2026-10-25-garage-
probikegarage-import-spec.md §10; the implementer makes them pass (or the
orchestrator decides otherwise and the test changes with that decision).
"""
import pytest

from .importers.probikegarage import build_plan
from .services.probikegarage_import import apply, verify
from .tests_probikegarage_import import C, NULL, UTC, clean_dump, interval, mount, part, service, strava_history, synthetic_dump, when


@pytest.fixture
def owner(db, django_user_model):
    return django_user_model.objects.create_user("pbg-review", password="synthetic-only")


def rows(report):
    return [row for block in report.blocks for row in block.rows]


def test_r043_1_calendar_rule_of_a_retired_part_is_compared_at_its_retirement(owner):
    """ProBikeGarage stops the elapsed-time count when a part is retired; Garage's calendar never stops
    (domain §14), so comparing at exported_at reports a false difference for every retired part."""
    dump = clean_dump()
    # Retired 01/02 10:00; reviewed on 20/01 10:00 every 30 days: 12 days used when it was retired.
    part(dump, "pads_old")["service_intervals"] = [interval("i-pads-days", "Revisar pastillas", "elapsed-time", 30 * 86400, True, 18 * 86400)]
    dump["services"].append(service("s-pads", "Revisar pastillas", when(1, 20), target="i-pads-days", parts=["pads_old"],
                                    intervals=["i-pads-days"]))
    apply(owner, dump, zone=UTC)
    strava_history(owner)
    report = verify(owner, dump)
    bad = [(row.label, row.kind, row.pbg, row.garage) for row in rows(report) if not row.ok]
    assert bad == [] and report.differences == 0, bad


def test_r043_2_rule_of_a_never_mounted_part_with_nothing_used_is_not_a_difference(owner):
    """Spec §2.5: without a mount Garage shows «Sin datos», «igual que PBG muestra el intervalo entero».
    The verification should not count that pair (next == threshold, no reference, never mounted) as a difference."""
    dump = clean_dump()
    part(dump, "roldana")["service_intervals"] = [interval("i-rold", "Limpiar", "distance", 1000000, True, 1000000)]
    apply(owner, dump, zone=UTC)
    strava_history(owner)
    report = verify(owner, dump)
    limpiar = [row for row in rows(report) if row.label.endswith("· Limpiar")]
    assert len(limpiar) == 1 and limpiar[0].ok, limpiar


def test_r043_3_rule_distance_tolerance_follows_the_usage_not_the_threshold(owner):
    """±0.5 % of a 3.000 km useful life is ±15 km: a whole ride of difference in the usage since the
    reference (here 10 km out of 110 km) must be reported, as it would be for the component totals."""
    dump = clean_dump()
    life = next(row for row in part(dump, "chain")["service_intervals"] if row["id"] == "i-life1")
    life["next"] = 2880000  # ProBikeGarage counted 120 km since the first mount; Garage counts 110 km
    apply(owner, dump, zone=UTC)
    strava_history(owner)
    report = verify(owner, dump)
    distance_life = [row for row in rows(report) if row.label == "Cadena sintética · Max life" and row.kind == "distance"]
    assert len(distance_life) == 1 and not distance_life[0].ok, distance_life


def test_r043_4_one_service_with_two_life_intervals_creates_one_replacement():
    """Several «Max life» of a part are one useful life (D2): one service listing two of them is one
    «Sustitución», never two identical interventions at the same instant."""
    dump = synthetic_dump()
    next(row for row in dump["services"] if row["id"] == "s-swap")["service_intervals_ids"] = ["i-life1", "i-life2"]
    plan = build_plan(dump)
    assert plan.ok, plan.errors
    swaps = [(event.component_id, event.service_type, event.performed_at) for event in plan.events if event.service_id == "s-swap"]
    assert len(swaps) == 1, swaps


def test_r043_5_nested_since_always_does_not_depend_on_the_order_of_the_dump():
    """A «since always» part inside another «since always» part resolves the same whatever the order of
    `installations`: today it is an error when the child comes first and valid when it comes last."""
    plans = []
    for child_first in (True, False):
        dump = synthetic_dump()
        child = mount("m-rold-fork", "roldana", parent="fork", added=NULL)
        if child_first:
            dump["installations"].insert(0, child)
        else:
            dump["installations"].append(child)
        plans.append(build_plan(dump))
    assert all(plan.ok for plan in plans), [[str(error) for error in plan.errors] for plan in plans]
    starts = [next(m.started_at for m in plan.installations if m.pbg_id == "m-rold-fork") for plan in plans]
    assert starts == [when(1, 3, 9), when(1, 3, 9)]  # the fork's own resolved start (first ride of the bike)


def test_r043_6_initial_usage_that_a_useful_life_will_not_count_is_warned():
    """The initial usage becomes a lifetime reading (D3), but a Garage useful life (a maintenance rule)
    only counts rides since its reference (domain §14: never lifetime readings). ProBikeGarage may
    count it: the report must say so for the part, not leave a silently longer useful life."""
    dump = synthetic_dump()
    part(dump, "pads_old")["service_intervals"] = [interval("i-pads-life", "Max life", "distance", 2000000, False, 620000)]
    plan = build_plan(dump)
    assert plan.ok, plan.errors
    messages = [warning.message for warning in plan.warnings if warning.table == "components" and warning.row_id == C["pads_old"]]
    assert any("uso inicial" in message and "vida útil" in message for message in messages), messages


def test_r043_7_the_target_interval_of_a_service_is_reset_even_when_it_is_not_listed():
    """target_type «service_interval» names the interval the service was registered for: with its
    component listed but no interval ids, the event must still reset that interval (type of the interval,
    title before the notes), not become a «Servicio» type that resets nothing."""
    dump = synthetic_dump()
    lube = next(row for row in dump["services"] if row["id"] == "s-lube")
    lube.update(title="Servicio", service_intervals_ids=[])
    plan = build_plan(dump)
    assert plan.ok, plan.errors
    events = [(event.component_id, event.service_type, event.interval_id, event.notes) for event in plan.events if event.service_id == "s-lube"]
    assert events == [(C["chain"], "Lubricar", "i-lube", "Servicio. Con cera")], events
