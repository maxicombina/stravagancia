"""Migration 0010 over pre-existing FIT rows (garage-030): additive except the widened CHECKs."""
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("garage", "0009_maintenancesnooze")]
AFTER = [("garage", "0010_strava_source")]


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


class StravaMigrationTests(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_fit_rows_survive_and_the_new_checks_apply(self):
        apps = migrate(BEFORE)
        user = apps.get_model("auth", "User").objects.create(username="migration-owner")
        Ride, Source, Run = (apps.get_model("garage", name) for name in ("Ride", "ActivitySource", "ImportRun"))
        start = datetime(2026, 1, 2, 10, tzinfo=datetime_timezone.utc)
        run = Run.objects.create(owner=user, file_hash="a" * 64, session_indices=[0], total=1, processed=1, cursor=1, state="completed")
        ride = Ride.objects.create(owner=user, started_at=start, distance_m=Decimal("1234.567"))
        source = Source.objects.create(owner=user, ride=ride, import_run=run, file_hash="a" * 64, session_index=0,
                                       parser_version="fitdecode-0.11.0", started_at=start, distance_m=Decimal("1234.567"))
        apps = migrate(AFTER)
        Source, Run = apps.get_model("garage", "ActivitySource"), apps.get_model("garage", "ImportRun")
        row = Source.objects.get(pk=source.pk)
        self.assertEqual((row.source_kind, row.external_id, row.gear_id, row.possible_duplicate, row.distance_m, row.ride_id),
                         ("fit", None, "", False, Decimal("1234.567"), ride.pk))
        run = Run.objects.get(pk=run.pk)
        self.assertEqual((run.source_kind, run.items_imported, run.items_skipped, run.total, run.cursor), ("fit", None, None, 1, 1))
        for changes in ({"source_kind": "strava"}, {"source_kind": "garmin"}, {"external_id": 1}, {"gear_id": "b1"}):
            with self.assertRaises(IntegrityError), transaction.atomic():
                Source.objects.filter(pk=source.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Run.objects.filter(pk=run.pk).update(source_kind="strava")  # a FIT manifest is never a Strava job
        Source.objects.create(owner_id=user.pk, ride_id=ride.pk, source_kind="strava", external_id=99, file_hash="b" * 64,
                              session_index=0, parser_version="strava-api-v3", started_at=start)
        self.assertEqual(Source.objects.filter(ride_id=ride.pk).count(), 2)
