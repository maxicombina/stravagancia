"""Migration 0012 (garage-030 phase 3) over existing rows: additive except the two replaced CHECKs, and reversible."""
from datetime import datetime, timezone as datetime_timezone
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("garage", "0011_category_icon")]
AFTER = [("garage", "0012_elevation_power")]
NEW_COLUMNS = {"ride": {"elevation_gain_m", "average_power_w", "max_power_w", "weighted_power_w", "energy_kj"},
               "activitysource": {"elevation_gain_m", "average_power_w", "max_power_w", "weighted_power_w", "energy_kj"},
               "itemusage": {"elevation_gain_m"}, "maintenancerule": {"elevation_gain_m"}, "maintenancesnooze": {"elevation_gain_m"}}


def migrate(targets):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(targets)
    return executor.loader.project_state(targets).apps


def columns(table):
    with connection.cursor() as cursor:
        return {column.name for column in connection.introspection.get_table_description(cursor, f"garage_{table}")}


class ElevationPowerMigrationTests(TransactionTestCase):
    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def rejects(self, model, pk, constraint, **values):
        with self.assertRaises(IntegrityError) as caught, transaction.atomic():
            model.objects.filter(pk=pk).update(**values)
        self.assertEqual(caught.exception.__cause__.diag.constraint_name, constraint)

    def test_existing_rows_survive_new_checks_apply_and_it_reverses(self):
        apps = migrate(BEFORE)
        get = lambda name: apps.get_model("garage", name)  # noqa: E731
        user = apps.get_model("auth", "User").objects.create(username="elevation-migration")
        start = datetime(2026, 1, 2, 10, tzinfo=datetime_timezone.utc)
        bike = get("Bike").objects.create(owner=user, name="Gravel")
        category = get("Category").objects.create(owner=user, name="Piezas")
        chain = get("Item").objects.create(owner=user, name="Cadena", category=category)
        ride = get("Ride").objects.create(owner=user, started_at=start, bike=bike, distance_m=Decimal("1234.567"))
        fit = get("ActivitySource").objects.create(owner=user, ride=ride, file_hash="a" * 64, session_index=0,
                                                   parser_version="fitdecode-0.11.0", started_at=start, distance_m=Decimal("1234.567"))
        strava = get("ActivitySource").objects.create(owner=user, ride=ride, source_kind="strava", external_id=99, file_hash="b" * 64,
                                                      session_index=0, parser_version="strava-api-v3", started_at=start,
                                                      distance_m=Decimal("1230"), gear_id="b1")
        usage = get("ItemUsage").objects.create(owner=user, item=chain, ride=ride, started_at=start, bike=bike,
                                                distance_m=Decimal("1234.567"), resolution=[])
        kind = get("ServiceType").objects.create(owner=user, name="Revisión")
        rule = get("MaintenanceRule").objects.create(owner=user, item=chain, service_type=kind, distance_m=Decimal("5000"))
        snooze = get("MaintenanceSnooze").objects.create(owner=user, rule=rule, started_at=start, reference_at=start, calendar_days=7)
        for table, added in NEW_COLUMNS.items():
            self.assertFalse(added & columns(table))

        apps = migrate(AFTER)
        get = lambda name: apps.get_model("garage", name)  # noqa: E731
        Ride, Source, Usage, Rule, Snooze = (get(name) for name in ("Ride", "ActivitySource", "ItemUsage", "MaintenanceRule",
                                                                    "MaintenanceSnooze"))
        for table, added in NEW_COLUMNS.items():
            self.assertTrue(added <= columns(table))
        for model, pk in ((Ride, ride.pk), (Source, fit.pk), (Source, strava.pk)):
            row = model.objects.get(pk=pk)
            self.assertEqual((row.elevation_gain_m, row.average_power_w, row.max_power_w, row.weighted_power_w, row.energy_kj), (None,) * 5)
        self.assertEqual(Source.objects.get(pk=strava.pk).distance_m, Decimal("1230"))
        self.assertEqual((Usage.objects.get(pk=usage.pk).elevation_gain_m, Usage.objects.get(pk=usage.pk).distance_m), (None, Decimal("1234.567")))
        self.assertEqual((Rule.objects.get(pk=rule.pk).elevation_gain_m, Rule.objects.get(pk=rule.pk).distance_m), (None, Decimal("5000")))
        self.assertEqual((Snooze.objects.get(pk=snooze.pk).elevation_gain_m, Snooze.objects.get(pk=snooze.pk).calendar_days), (None, 7))

        # Range CHECKs on the new columns (elevation may be zero, never negative).
        Ride.objects.filter(pk=ride.pk).update(elevation_gain_m=0)
        self.rejects(Ride, ride.pk, "garage_ride_elevation_gain_m_valid", elevation_gain_m=-1)
        self.rejects(Ride, ride.pk, "garage_ride_average_power_w_valid", average_power_w=-1)
        self.rejects(Source, fit.pk, "garage_activitysource_energy_kj_valid", energy_kj=-1)
        self.rejects(Source, strava.pk, "garage_activitysource_weighted_power_w_valid", weighted_power_w=-1)
        self.rejects(Usage, usage.pk, "garage_itemusage_elevation_gain_m_valid", elevation_gain_m=-1)
        # The replaced "at least one" CHECKs accept elevation alone and still reject nothing at all.
        Rule.objects.filter(pk=rule.pk).update(distance_m=None, elevation_gain_m=Decimal("8000"))
        Snooze.objects.filter(pk=snooze.pk).update(calendar_days=None, elevation_gain_m=Decimal("700"))
        self.rejects(Rule, rule.pk, "garage_maintenancerule_has_threshold", elevation_gain_m=None)
        self.rejects(Snooze, snooze.pk, "garage_snooze_has_amount", elevation_gain_m=None)
        self.rejects(Rule, rule.pk, "garage_rule_elevation_gain_m_positive", elevation_gain_m=0)
        self.rejects(Snooze, snooze.pk, "garage_snooze_elevation_gain_m_positive", elevation_gain_m=0)

        # Reversible once no row depends on elevation alone (the old CHECKs come back).
        Rule.objects.filter(pk=rule.pk).update(distance_m=Decimal("5000"), elevation_gain_m=None)
        Snooze.objects.filter(pk=snooze.pk).update(calendar_days=7)
        apps = migrate(BEFORE)
        for table, added in NEW_COLUMNS.items():
            self.assertFalse(added & columns(table))
        Rule, Snooze = apps.get_model("garage", "MaintenanceRule"), apps.get_model("garage", "MaintenanceSnooze")
        self.assertEqual(apps.get_model("garage", "ActivitySource").objects.filter(ride_id=ride.pk).count(), 2)
        self.assertEqual(apps.get_model("garage", "ItemUsage").objects.get(pk=usage.pk).distance_m, Decimal("1234.567"))
        self.assertEqual(Rule.objects.get(pk=rule.pk).distance_m, Decimal("5000"))
        self.assertEqual(Snooze.objects.get(pk=snooze.pk).calendar_days, 7)
        self.rejects(Rule, rule.pk, "garage_maintenancerule_has_threshold", distance_m=None)
