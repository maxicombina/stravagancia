"""Synthetic FIT replay, literal dry-run and private history workflows."""
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
import time
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, TransactionTestCase
from django.db import close_old_connections, connection
from django.urls import reverse

from .history_forms import RideCorrectionForm
from .importers.fit import parse_fit
from .models import ActivitySource, Bike, ImportRun, Ride
from .ride_values import RIDE_FIELDS
from .services import import_history
from .services.import_history import (assign_pending_bikes, cancel_fit_import, coverage, history_queryset,
                                     preview_fit, resume_fit_import, start_fit_import)
from .services.ownership import InventoryNotFound, create_inventory
from .services.rides import correct_ride, create_manual_ride, import_fit_session
from .tests_fit_import import activity, session


def instant(day):
    return datetime(2026, 1, day, 10, tzinfo=timezone.utc)


def upload(raw=None):
    return SimpleUploadedFile('synthetic.fit', activity() if raw is None else raw, content_type='application/octet-stream')


class HistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user('history-owner')
        cls.other = get_user_model().objects.create_user('history-other')
        cls.admin = get_user_model().objects.create_superuser('history-admin', 'history@example.test', 'test-only')
        cls.bike = create_inventory(cls.owner, Bike, name='Own bike')
        cls.foreign_bike = create_inventory(cls.other, Bike, name='PRIVATE bike')
        cls.foreign_ride = create_manual_ride(cls.other, started_at=instant(1), name='PRIVATE ride')

    def setUp(self):
        self.client.force_login(self.owner)

    def url(self, suffix, *args):
        return reverse('garage:history' + ('-' + suffix if suffix else ''), args=args)

    def begin(self, raw=None, **kwargs):
        raw = raw or activity()
        preview = preview_fit(self.owner, raw, session_indices=kwargs.pop('session_indices', None))
        return start_fit_import(self.owner, raw, preview.token, **kwargs)

    def modes(self, **changes):
        data = {name + '_mode': 'keep' for name in RIDE_FIELDS}
        data.update(time_zone='UTC', confirm_history='on')
        data.update(changes)
        return data

    def test_preview_has_no_writes_even_session_and_http_view(self):
        initial = {model: model.objects.count() for model in (Ride, ImportRun, ActivitySource)}
        preview = preview_fit(self.owner, activity())
        self.assertTrue(preview.token)
        self.assertEqual(preview.selected_indices, (0,))
        writes = []
        def monitor(execute, sql, params, many, context):
            if sql.lstrip().split()[0].upper() in {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER', 'TRUNCATE'}:
                writes.append(True)
            return execute(sql, params, many, context)
        before_session = dict(self.client.session)
        with connection.execute_wrapper(monitor):
            preview_fit(self.owner, activity())
            response = self.client.post(self.url('preview'), {'file': upload(), 'time_zone': 'UTC'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['preview'].token)
        self.assertEqual(writes, [])
        self.assertEqual(dict(self.client.session), before_session)
        self.assertEqual({model: model.objects.count() for model in initial}, initial)

    def test_multisession_preview_selection_explicit_and_signed(self):
        raw = activity(session(), session(start=1_100_010_000))
        preview = preview_fit(self.owner, raw)
        self.assertIsNone(preview.token)
        self.assertEqual(preview.selected_indices, ())
        selected = preview_fit(self.owner, raw, session_indices=[1])
        manifest = signing.loads(selected.token, salt=import_history.PREVIEW_SALT)
        self.assertEqual(manifest['sessions'], [1])
        self.assertNotIn('file', manifest)
        self.assertNotIn('name', manifest)
        run = start_fit_import(self.owner, raw, selected.token)
        self.assertEqual(run.session_indices, [1])
        self.assertEqual(ActivitySource.objects.get().session_index, 1)

    def test_owner_token_modified_token_expired_and_hash_mismatch_no_writes(self):
        preview = preview_fit(self.owner, activity())
        for actor, raw, token in [(self.other, activity(), preview.token),
                                  (self.owner, activity(), preview.token + 'x'),
                                  (self.owner, activity(session(distance=12)), preview.token)]:
            with self.assertRaises(ValidationError):
                start_fit_import(actor, raw, token)
        with patch('django.core.signing.time.time', return_value=time.time() + 3602):
            with self.assertRaises(ValidationError):
                start_fit_import(self.owner, activity(), preview.token)
        self.assertFalse(ImportRun.objects.exists())
        self.assertFalse(ActivitySource.objects.exists())

    def test_preview_requested_range_is_half_open_and_old_fields_detected(self):
        raw = activity()
        parsed = parse_fit(raw)
        row = parsed.sessions[0]
        existing, source = import_fit_session(self.owner, file_hash=parsed.file_hash, session_index=0,
            parser_version='older-parser', observations={'started_at': row.started_at, 'sport_type': 'cycling'})
        self.assertIsNone(existing.distance_m)
        preview = preview_fit(self.owner, raw, requested_from=row.started_at)
        self.assertEqual(preview.sessions[0].existing_ride_id, existing.pk)
        with self.assertRaises(ValidationError):
            preview_fit(self.owner, raw, requested_to=row.started_at)
        run = start_fit_import(self.owner, raw, preview.token)
        self.assertEqual(run.state, 'completed')
        existing.refresh_from_db()
        self.assertEqual(existing.distance_m, row.distance_m)
        self.assertEqual(ActivitySource.objects.count(), 1)

    def test_candidate_matches_are_not_merged_automatically(self):
        parsed = parse_fit(activity()).sessions[0]
        candidate = create_manual_ride(self.owner, started_at=parsed.started_at,
            sport_type='cycling', distance_m=parsed.distance_m)
        preview = preview_fit(self.owner, activity())
        self.assertEqual(preview.sessions[0].candidate_count, 1)
        self.begin()
        self.assertEqual(Ride.objects.filter(owner=self.owner).count(), 2)
        self.assertTrue(Ride.objects.filter(pk=candidate.pk).exists())

    def test_resumable_manifest_survives_browser_loss_and_cursor_is_position(self):
        raw = activity(session(sport=1), session(start=1_100_010_000), session(sport=1), session(sport=1), session(start=1_100_040_000))
        run = self.begin(raw, session_indices=[1, 4], budget=1)
        self.assertEqual((run.state, run.cursor, run.processed, run.total), ('paused', 1, 1, 2))
        self.assertEqual(run.session_indices, [1, 4])
        fresh = Client()
        fresh.force_login(self.owner)
        self.assertContains(fresh.get(self.url('run', run.pk)), '1/2')
        self.assertEqual(fresh.post(self.url('run', run.pk), {'file': upload(raw)}).status_code, 302)
        run.refresh_from_db()
        self.assertEqual((run.state, run.cursor), ('completed', 2))
        self.assertEqual(set(ActivitySource.objects.values_list('session_index', flat=True)), {1, 4})
        # The durable manifest has no relationship to the expired preview token.
        with patch('django.core.signing.time.time', return_value=time.time() + 7200):
            self.assertEqual(resume_fit_import(self.owner, run.pk, raw).pk, run.pk)

    def test_resume_different_or_corrupt_file_keeps_checkpoint(self):
        raw = activity(session(), session(start=1_100_010_000))
        run = self.begin(raw, session_indices=[0, 1], budget=1)
        before = (run.cursor, run.processed, run.state)
        for bad in (raw[:-1], activity(session(), session(start=1_100_010_000, distance=10))):
            with self.assertRaises(ValidationError):
                resume_fit_import(self.owner, run.pk, bad)
        run.refresh_from_db()
        self.assertEqual((run.cursor, run.processed, run.state), before)
        self.assertEqual(ActivitySource.objects.count(), 1)

    def test_unexpected_crash_keeps_committed_prefix_and_retry_idempotent(self):
        raw = activity(session(), session(start=1_100_010_000))
        original = import_history.import_fit_session
        calls = []
        def crash(owner, **values):
            calls.append(values)
            if len(calls) == 2:
                raise RuntimeError('synthetic crash')
            return original(owner, **values)
        with patch('garage.services.import_history.import_fit_session', side_effect=crash):
            with self.assertRaisesRegex(RuntimeError, 'synthetic crash'):
                self.begin(raw, session_indices=[0, 1])
        run = ImportRun.objects.get()
        self.assertEqual((run.cursor, run.processed), (1, 1))
        first_source = ActivitySource.objects.get()
        finished = resume_fit_import(self.owner, run.pk, raw)
        self.assertEqual(finished.state, 'completed')
        self.assertEqual(ActivitySource.objects.count(), 2)
        self.assertTrue(ActivitySource.objects.filter(pk=first_source.pk).exists())

    def test_expected_failure_progress_counts_unique_positions(self):
        raw = activity(session(), session(start=1_100_010_000))
        original = import_history.import_fit_session
        def failure(owner, **values):
            if values['session_index'] == 1:
                raise ValidationError('private details must not enter errors')
            return original(owner, **values)
        with patch('garage.services.import_history.import_fit_session', side_effect=failure):
            run = self.begin(raw, session_indices=[0, 1])
            self.assertEqual((run.state, run.cursor, run.processed), ('failed', 1, 2))
            self.assertEqual(run.errors, [{'code': 'conflict', 'session_index': 1}])
            repeated = resume_fit_import(self.owner, run.pk, raw)
            self.assertEqual(repeated.processed, 2)
        self.assertEqual(ActivitySource.objects.count(), 1)
        self.assertEqual(resume_fit_import(self.owner, run.pk, raw).state, 'completed')
        self.assertEqual(ActivitySource.objects.count(), 2)

    def test_terminal_run_never_reads_or_imports_and_cancel_keeps_prefix(self):
        raw = activity(session(), session(start=1_100_010_000))
        run = self.begin(raw, session_indices=[0, 1], budget=1)
        cancel_fit_import(self.owner, run.pk)
        stream = SimpleNamespace(read=lambda size: self.fail('terminal job touched uploaded stream'))
        self.assertEqual(resume_fit_import(self.owner, run.pk, stream).state, 'cancelled')
        self.assertEqual(ActivitySource.objects.count(), 1)
        completed = self.begin(activity())
        self.assertEqual(resume_fit_import(self.owner, completed.pk, stream).state, 'completed')

    def test_invalid_fit_and_bad_selection_never_create_job(self):
        for raw in (activity()[:-1], activity() + b'x'):
            with self.assertRaises(ValidationError):
                preview_fit(self.owner, raw)
        with self.assertRaises(ValidationError):
            preview_fit(self.owner, activity(), session_indices=[1])
        self.assertFalse(ImportRun.objects.exists())

    def test_batch_owner_atomic_manual_null_and_known_bike_preserved(self):
        first = create_manual_ride(self.owner, started_at=instant(1))
        # No bike key denotes no decision; NULL presence denotes intentional unknown.
        protected = create_manual_ride(self.owner, started_at=instant(1), bike=None)
        assigned = create_manual_ride(self.owner, started_at=instant(1), bike=self.bike.pk)
        with self.assertRaises(InventoryNotFound):
            assign_pending_bikes(self.owner, [first.pk, self.foreign_ride.pk], self.bike)
        first.refresh_from_db()
        self.assertIsNone(first.bike_id)
        result = assign_pending_bikes(self.owner, [first.pk, protected.pk, assigned.pk], self.bike)
        self.assertEqual(result.changed_ids, (first.pk,))
        self.assertEqual(set(result.skipped_ids), {protected.pk, assigned.pk})
        first.refresh_from_db()
        self.assertEqual(first.bike_id, self.bike.pk)
        self.assertEqual(first.field_provenance['bike']['kind'], 'manual')
        second = create_manual_ride(self.owner, started_at=instant(2))
        assign_pending_bikes(self.owner, [second.pk], None)
        second.refresh_from_db()
        self.assertIn('bike', second.manual_overrides)
        self.assertIsNone(second.manual_overrides['bike'])

    def test_batch_api_foreign_destination_rejected_and_empty_invalid(self):
        ride = create_manual_ride(self.owner, started_at=instant(1))
        with self.assertRaises(InventoryNotFound):
            assign_pending_bikes(self.owner, [ride.pk], self.foreign_bike.pk)
        with self.assertRaises(ValidationError):
            assign_pending_bikes(self.owner, [], self.bike)
        ride.refresh_from_db()
        self.assertIsNone(ride.bike_id)

    def test_manual_create_decimal_ianna_nulls_and_edit_keep_null(self):
        response = self.client.post(self.url('manual-create'), {'started_at': '2026-01-01T11:00:00.123456',
            'time_zone': 'Europe/Madrid', 'name': 'Manual', 'distance_m': '12.345', 'timer_time_s': '1.001', 'notes': 'own note'})
        self.assertEqual(response.status_code, 302)
        ride = Ride.objects.get(owner=self.owner, name='Manual')
        self.assertEqual(ride.started_at, instant(1).replace(microsecond=123456))
        self.assertEqual(ride.distance_m, Decimal('12.345'))
        self.assertIsNone(ride.moving_time_s)
        response = self.client.post(self.url('manual-edit', ride.pk), self.modes(distance_m_mode='set', distance_m=''))
        self.assertEqual(response.status_code, 302)
        ride.refresh_from_db()
        self.assertIsNone(ride.manual_overrides['distance_m'])
        stamp = ride.field_provenance['distance_m']
        self.assertEqual(self.client.post(self.url('manual-edit', ride.pk), self.modes()).status_code, 302)
        ride.refresh_from_db()
        self.assertIsNone(ride.manual_overrides['distance_m'])
        self.assertEqual(ride.field_provenance['distance_m'], stamp)

    def test_manual_edit_confirm_restore_source_and_whole_operation_rollback(self):
        run = self.begin()
        ride = Ride.objects.get(owner=self.owner)
        correct_ride(self.owner, ride.pk, distance_m=None)
        response = self.client.post(self.url('manual-edit', ride.pk), self.modes(confirm_history='', distance_m_mode='source'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('confirm_history', response.context['form'].errors)
        response = self.client.post(self.url('manual-edit', ride.pk), self.modes(distance_m_mode='source'))
        self.assertEqual(response.status_code, 302)
        ride.refresh_from_db()
        self.assertEqual(ride.distance_m, parse_fit(activity()).sessions[0].distance_m)
        manual = create_manual_ride(self.owner, started_at=instant(1), distance_m=Decimal('5'))
        response = self.client.post(self.url('manual-edit', manual.pk), self.modes(started_at_mode='source', distance_m_mode='set', distance_m='88'))
        self.assertEqual(response.status_code, 200)
        manual.refresh_from_db()
        self.assertEqual(manual.distance_m, Decimal('5'))
        self.assertEqual(manual.started_at, instant(1))

    def test_manual_foreign_fk_bad_precision_dst_and_date_required(self):
        for changes in ({'bike': str(self.foreign_bike.pk)}, {'distance_m': '1.0001'},
                        {'started_at': ''}, {'started_at': '2026-03-29T02:30:00', 'time_zone': 'Europe/Madrid'}):
            data = {'started_at': '2026-01-01T10:00:00', 'time_zone': 'UTC'}
            data.update(changes)
            response = self.client.post(self.url('manual-create'), data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['form'].errors)
        self.assertFalse(Ride.objects.filter(owner=self.owner).exists())

    def test_coverage_observed_range_unknown_metrics_not_completeness(self):
        create_manual_ride(self.owner, started_at=instant(1), distance_m=0)
        create_manual_ride(self.owner, started_at=instant(2), distance_m=None)
        stats = coverage(self.owner, requested_from=instant(1), requested_to=instant(2))
        self.assertEqual(stats['observed'], 1)
        self.assertEqual(stats['missing_fields']['distance_m'], 0)
        self.assertEqual(stats['missing_fields']['moving_time_s'], 1)
        self.assertEqual(stats['completeness'], 'unknown')
        self.assertEqual(history_queryset(self.owner, pending=True).count(), 2)
        response = self.client.get(self.url(''))
        self.assertContains(response, 'Completitud del histórico:')
        self.assertContains(response, 'desconocida')
        self.assertNotContains(response, 'PRIVATE ride')

    def test_private_run_routes_superuser_auth_and_csrf(self):
        run = self.begin()
        self.client.logout()
        self.assertEqual(self.client.get(self.url('')).status_code, 302)
        for actor in (self.other, self.admin):
            self.client.force_login(actor)
            for suffix in ('run', 'cancel'):
                self.assertEqual(self.client.post(self.url(suffix, run.pk), {'file': upload()}).status_code, 404)
            self.assertEqual(self.client.get(self.url('run', run.pk)).status_code, 404)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        for suffix in ('preview', 'execute', 'manual-create', 'bike-batch'):
            self.assertEqual(client.post(self.url(suffix), {}).status_code, 403)
        self.assertEqual(client.post(self.url('cancel', run.pk)).status_code, 403)
        self.assertEqual(client.get(self.url('execute')).status_code, 405)
        self.assertEqual(client.get(self.url('cancel', run.pk)).status_code, 405)

    def test_execute_http_reupload_bound_and_foreign_corrections_denied(self):
        preview = self.client.post(self.url('preview'), {'file': upload(), 'time_zone': 'UTC'}).context['preview']
        response = self.client.post(self.url('execute'), {'file': upload(), 'preview_token': preview.token})
        self.assertEqual(response.status_code, 302)
        self.assertContains(self.client.get(response.url), '1/1')
        self.assertEqual(self.client.get(self.url('manual-edit', self.foreign_ride.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('manual-edit', self.foreign_ride.pk), self.modes()).status_code, 404)

    def test_withdraw_source_confirm_owner_and_get_no_changes(self):
        self.begin()
        source = ActivitySource.objects.get()
        self.assertEqual(self.client.get(self.url('source-withdraw', source.pk)).status_code, 200)
        source.refresh_from_db()
        self.assertIsNone(source.withdrawn_at)
        self.assertEqual(self.client.post(self.url('source-withdraw', source.pk), {}).status_code, 200)
        self.assertEqual(self.client.post(self.url('source-withdraw', source.pk), {'confirm': 'on'}).status_code, 302)
        source.refresh_from_db()
        self.assertIsNotNone(source.withdrawn_at)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(self.url('source-withdraw', source.pk), {'confirm': 'on'}).status_code, 404)

    def test_pagination_and_escaped_notes(self):
        for number in range(21):
            create_manual_ride(self.owner, started_at=instant(1), name=f'Ride {number}')
        self.assertEqual(len(self.client.get(self.url('') + '?page=2').context['page']), 1)
        ride = create_manual_ride(self.owner, started_at=instant(1), name='<script>alert(1)</script>', notes='<script>notes</script>')
        response = self.client.get(self.url('manual-edit', ride.pk))
        self.assertNotContains(response, '<script>notes</script>')
        self.assertContains(response, '&lt;script&gt;')

    def test_preview_unicode_digit_is_validation_error_not_500(self):
        response = self.client.post(self.url('preview'), {'file': upload(), 'time_zone': 'UTC', 'session_indices': '²'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('session_indices', response.context['form'].errors)
        self.assertFalse(ImportRun.objects.exists())


class HistoryConcurrencyTests(TransactionTestCase):
    def test_concurrent_resume_serializes_checkpoint_without_duplicate_sources(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        owner = get_user_model().objects.create_user('concurrent-history-owner')
        raw = activity(session(), session(start=1_100_010_000), session(start=1_100_020_000))
        preview = preview_fit(owner, raw, session_indices=[0, 1, 2])
        run = start_fit_import(owner, raw, preview.token, budget=1)
        barrier = Barrier(2)
        def worker():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=owner.pk)
                barrier.wait(timeout=15)
                return resume_fit_import(actor, run.pk, raw, budget=1).state
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        run.refresh_from_db()
        self.assertEqual((run.state, run.cursor, run.processed), ('completed', 3, 3))
        self.assertEqual(ActivitySource.objects.filter(owner=owner).count(), 3)
        self.assertEqual(Ride.objects.filter(owner=owner).count(), 3)
        self.assertTrue(all(state in ('paused', 'completed') for state in results))

    def test_cancel_during_resume_parse_prevents_any_later_checkpoint(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        owner = get_user_model().objects.create_user('cancel-history-owner')
        raw = activity(session(), session(start=1_100_010_000))
        preview = preview_fit(owner, raw, session_indices=[0, 1])
        run = start_fit_import(owner, raw, preview.token, budget=1)
        parsing, continue_parse = Event(), Event()
        original = import_history.parse_fit
        def delayed_parse(source):
            parsing.set()
            if not continue_parse.wait(timeout=15):
                raise RuntimeError('synthetic parse synchronization timeout')
            return original(source)
        def worker():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=owner.pk)
                return resume_fit_import(actor, run.pk, raw).state
            finally:
                close_old_connections()
        with patch('garage.services.import_history.parse_fit', side_effect=delayed_parse):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(worker)
                try:
                    self.assertTrue(parsing.wait(timeout=15))
                    cancel_fit_import(owner, run.pk)
                finally:
                    continue_parse.set()
                self.assertEqual(future.result(timeout=15), 'cancelled')
        run.refresh_from_db()
        self.assertEqual((run.state, run.cursor), ('cancelled', 1))
        self.assertEqual(ActivitySource.objects.filter(owner=owner).count(), 1)
