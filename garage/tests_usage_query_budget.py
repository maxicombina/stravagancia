from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from .models import Item, ItemUsage, Ride, UsageMaterializationState
from .services.usage import rebuild_usage, summarize_item_usage
from .services.usage_profiles import resolve_ride_usage
from .tests_usage_materialization import instant, profile, usage


@pytest.mark.django_db
def test_rebuild_300_rides_20_items_has_bounded_queries_and_same_resolution(usage):
    # Synthetic bulk fixture stands for pre-existing Garage data after migration;
    # it is not a public write route, real FIT content or legacy Activity data.
    items = Item.objects.bulk_create([Item(owner=usage.owner, category=usage.helmet.category, name=f"Equipment {index}")
                                     for index in range(20)])
    profile(usage, items)
    provenance = {"distance_m": {"kind": "manual", "source_id": None, "updated_at": instant().isoformat()}}
    rides = Ride.objects.bulk_create([Ride(owner=usage.owner, started_at=instant() + timedelta(minutes=index),
                                          distance_m=Decimal("123.456"), moving_time_s=None,
                                          field_provenance=provenance) for index in range(300)])
    UsageMaterializationState.objects.filter(owner=usage.owner).delete()
    with CaptureQueriesContext(connection) as queries:
        result = rebuild_usage(usage.owner)
    assert result.created == 6000 and result.updated == result.deleted == 0
    assert len(queries) <= 55, f"{len(queries)} queries for 300 rides × 20 items"
    for own in (rides[0], rides[149], rides[-1]):
        assert set(ItemUsage.objects.filter(ride=own).values_list("item_id", flat=True)) == resolve_ride_usage(usage.owner, own.pk).item_ids == {item.pk for item in items}
    with CaptureQueriesContext(connection) as queries:
        repeated = rebuild_usage(usage.owner)
    assert repeated.unchanged == 6000 and repeated.created == repeated.updated == repeated.deleted == 0
    assert len(queries) <= 30, f"{len(queries)} queries for an unchanged reconstruction"
    with CaptureQueriesContext(connection) as queries:
        summary = summarize_item_usage(usage.owner, items[0].pk, metric="distance_m", scope="lifetime", at=instant(20))
    assert summary.materialization_current and summary.reading.observed == Decimal("37036.800")
    assert summary.reading.total is None and not summary.reading.coverage_complete
    assert len(queries) <= 20, f"{len(queries)} queries for one item total, independent of ride count"
