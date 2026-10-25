"""Real binary FIT fixtures generated from synthetic constants, never user files."""
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO, StringIO
import struct
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase, TestCase

from .importers.fit import (parse_fit, select_sessions, import_fit, decimal_metric,
                           MAX_FILE_BYTES, PARSER_VERSION, read_bounded)
from .models import ActivitySource, Bike, ImportRun, Ride
from .services.ownership import InventoryNotFound, create_inventory
from .services.rides import correct_ride, create_import_run, withdraw_source


# Independent bitwise CRC encoder, intentionally not using decoder utilities.
def crc16(data):
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0xA001 if crc & 1 else 0)
    return crc


def message(global_num, fields, *, big_endian=False, developer=()):
    """Each field is (number, FIT base type, encoded bytes). Redefine local0."""
    endian = '>' if big_endian else '<'
    definition = bytes([0x40 | (0x20 if developer else 0), 0, int(big_endian)])
    definition += struct.pack(endian + 'H', global_num) + bytes([len(fields)])
    definition += b''.join(bytes([number, len(value), base_type]) for number, base_type, value in fields)
    if developer:
        definition += bytes([len(developer)]) + b''.join(bytes([number, len(value), index]) for number, index, value in developer)
    return definition + b'\x00' + b''.join(value for _, _, value in fields) + b''.join(value for _, _, value in developer)


def uint32(number, value, endian='<'):
    return (number, 0x86, struct.pack(endian + 'I', value))


def session(*, start=1_100_000_000, sport=2, distance=123456789, timer=1234567,
            elapsed=1240567, moving=None, extra=(), big_endian=False, developer=()):
    endian = '>' if big_endian else '<'
    fields = []
    if start is not None:
        fields.append(uint32(2, start, endian))
    if sport is not None:
        fields.append((5, 0, bytes([sport])))
    for number, value in [(9, distance), (8, timer), (7, elapsed), (59, moving)]:
        if value is not None:
            fields.append(uint32(number, value, endian))
    return message(18, fields + list(extra), big_endian=big_endian, developer=developer)


def container(body, header_size=14):
    header = struct.pack('<BBHI4s', header_size, 0x20, 2170, len(body), b'.FIT')
    if header_size == 14:
        header += struct.pack('<H', crc16(header))
    contents = header + body
    return contents + struct.pack('<H', crc16(contents))


def activity(*sessions, header_size=14, extra=b'', file_type=4):
    file_id = message(0, [(0, 0, bytes([file_type]))])
    return container(file_id + extra + b''.join(sessions or (session(),)), header_size)


class FitParserTests(SimpleTestCase):
    def assert_code(self, code, function, *args, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_headers_endianness_crc_and_fractional_metrics(self):
        for header in (12, 14):
            for big_endian in (False, True):
                parsed = parse_fit(activity(session(big_endian=big_endian), header_size=header))
                row = select_sessions(parsed)[0]
                self.assertEqual(row.distance_m, Decimal('1234567.890'))
                self.assertEqual(row.timer_time_s, Decimal('1234.567'))
                self.assertEqual(row.elapsed_time_s, Decimal('1240.567'))
                self.assertIsNone(row.moving_time_s)
                self.assertEqual(row.started_at.utcoffset().total_seconds(), 0)
                self.assertEqual(parsed.parser_version, PARSER_VERSION)
                self.assertEqual(len(parsed.file_hash), 64)

    def test_explicit_moving_distinct_from_timer_and_missing_metrics_null(self):
        row = parse_fit(activity(session(moving=1000001))).sessions[0]
        self.assertEqual(row.moving_time_s, Decimal('1000.001'))
        self.assertNotEqual(row.moving_time_s, row.timer_time_s)
        row = parse_fit(activity(session(distance=None, timer=None, elapsed=None))).sessions[0]
        self.assertIsNone(row.distance_m)
        self.assertIsNone(row.timer_time_s)
        self.assertIsNone(row.elapsed_time_s)
        row = parse_fit(activity(session(distance=0, timer=0, elapsed=0, moving=0))).sessions[0]
        self.assertEqual(row.distance_m, 0)
        self.assertEqual(row.moving_time_s, 0)

    def test_invalid_fit_sentinels_are_null(self):
        row = parse_fit(activity(session(distance=0xFFFFFFFF, timer=0xFFFFFFFF, elapsed=0xFFFFFFFF))).sessions[0]
        self.assertIsNone(row.distance_m)
        self.assertIsNone(row.timer_time_s)
        self.assertIsNone(row.elapsed_time_s)
        self.assert_code('fit_start_required', parse_fit, activity(session(start=0xFFFFFFFF)))

    def test_crc_payload_footer_and_header_corruption(self):
        original = activity()
        for position in (3, len(original) - 3, len(original) - 1):
            broken = bytearray(original)
            broken[position] ^= 1
            self.assert_code('fit_decode_error', parse_fit, bytes(broken))

    def test_truncation_trailing_and_concatenated_files_rejected(self):
        original = activity()
        for cut in (1, 2, 8, len(original) - 14):
            self.assert_code('fit_invalid_size', parse_fit, original[:-cut])
        for extra in (b'\x00', original):
            self.assert_code('fit_invalid_size', parse_fit, original + extra)
        self.assert_code('fit_invalid_header', parse_fit, b'not fit')
        # Correct container CRC but truncated internal data record.
        body = message(0, [(0, 0, b'\x04')]) + session()[:-1]
        self.assert_code('fit_decode_error', parse_fit, container(body))

    def test_decoder_boundary_does_not_swallow_our_programming_errors(self):
        with patch('garage.importers.fit.session_from_message', side_effect=AssertionError('own normalization bug')):
            with self.assertRaisesRegex(AssertionError, 'own normalization bug'):
                parse_fit(activity())

    def test_internal_truncation_rejected_with_python_optimized(self):
        broken = container(message(0, [(0, 0, b'\x04')]) + session()[:-1])
        code = """import sys
from django.core.exceptions import ValidationError
from garage.importers.fit import parse_fit
try:
    parse_fit(sys.stdin.buffer.read())
except ValidationError as error:
    sys.exit(0 if error.code == 'fit_decode_error' else 2)
sys.exit(3)
"""
        process = subprocess.run([sys.executable, '-O', '-c', code], input=broken,
                                 capture_output=True, timeout=15, check=False)
        self.assertEqual(process.returncode, 0, process.stderr.decode())

    def test_invalid_activity_start_sport_and_sessions(self):
        self.assert_code('fit_not_activity', parse_fit, activity(file_type=5))
        self.assert_code('fit_not_activity', parse_fit, container(session()))
        self.assert_code('fit_no_sessions', parse_fit, container(message(0, [(0, 0, b'\x04')])))
        for start in (None, 1000):
            self.assert_code('fit_start_required', parse_fit, activity(session(start=start)))
        for sport in (1, 0, 254, None):
            self.assert_code('fit_unsupported_sport', select_sessions, parse_fit(activity(session(sport=sport))))

    def test_multisession_selection_original_indices_and_no_lap_double_count(self):
        lap = message(19, [uint32(9, 9999999)])
        parsed = parse_fit(activity(session(sport=1), session(start=1_100_010_000), extra=lap))
        self.assertEqual(len(parsed.sessions), 2)
        self.assert_code('fit_selection_required', select_sessions, parsed)
        self.assertEqual(select_sessions(parsed, [1])[0].session_index, 1)
        self.assertEqual(select_sessions(parsed, [1])[0].distance_m, Decimal('1234567.89'))
        for selection in ([], [1, 1], [2], [-1], [True], '1', {1}):
            self.assert_code('fit_invalid_selection', select_sessions, parsed, selection)
        self.assert_code('fit_unsupported_sport', select_sessions, parsed, [0, 1])

    def test_unknown_and_private_record_fields_do_not_leave_parser(self):
        private_record = message(20, [uint32(0, 54321), (3, 2, b'\x90'), uint32(200, 87654)])
        parsed = parse_fit(activity(session(extra=[uint32(250, 88888), uint32(3, 77777)]), extra=private_record))
        self.assertEqual(set(parsed.sessions[0].observations()), {'started_at', 'sport_type', 'distance_m', 'moving_time_s', 'timer_time_s', 'elapsed_time_s',
                                                                 'elevation_gain_m', 'average_power_w', 'max_power_w', 'weighted_power_w', 'energy_kj'})
        self.assertNotIn('88888', repr(parsed))
        self.assertNotIn('77777', repr(parsed))
        self.assertNotIn('54321', repr(parsed))

    def test_developer_field_spoofing_native_name_is_ignored(self):
        dev_id = message(207, [(3, 2, b'\x00'), (1, 0x0D, bytes(range(16)))])
        description = message(206, [(0, 2, b'\x00'), (1, 2, b'\x09'), (2, 2, b'\x86'),
                                   (3, 7, b'total_distance\x00')])
        encoded = activity(session(developer=[(9, 0, struct.pack('<I', 22222))]), extra=dev_id + description)
        row = parse_fit(encoded).sessions[0]
        self.assertEqual(row.distance_m, Decimal('1234567.89'))
        self.assertNotIn('22222', repr(row))

    def test_duplicate_native_and_float_metrics_rejected(self):
        self.assert_code('fit_duplicate_field', parse_fit, activity(session(extra=[uint32(9, 4)])))
        self.assert_code('fit_invalid_metric', parse_fit, activity(session(distance=None, extra=[(9, 0x88, struct.pack('<f', 1.5))])))

    def test_decimal_scale_offset_exact_and_precision_rejected(self):
        field = SimpleNamespace(raw_value=12345, field=SimpleNamespace(scale=1000, offset=2))
        self.assertEqual(decimal_metric(field), Decimal('10.345'))
        field.field.scale = 10000
        field.field.offset = 0
        with self.assertRaises(ValidationError):
            decimal_metric(field)
        for scale in (0, -1, 'NaN', 'Infinity'):
            field.field.scale = scale
            self.assert_code('fit_invalid_metric', decimal_metric, field)
        field.raw_value = 1.5
        self.assert_code('fit_invalid_metric', decimal_metric, field)

    def test_bounded_input_stream_and_resource_caps(self):
        raw = activity()
        stream = BytesIO(raw)
        self.assertEqual(parse_fit(stream).sessions, parse_fit(raw).sessions)
        self.assertFalse(stream.closed)
        self.assertEqual(read_bounded(bytearray(raw)), raw)
        self.assertEqual(read_bounded(memoryview(raw)), raw)
        self.assert_code('fit_invalid_input', parse_fit, '/private/tmp/file.fit')
        self.assert_code('fit_invalid_input', parse_fit, StringIO('FIT'))
        with patch('garage.importers.fit.MAX_FILE_BYTES', 100):
            self.assert_code('fit_too_large', parse_fit, b'x' * 101)
            self.assert_code('fit_too_large', parse_fit, BytesIO(b'x' * 101))
            # len(view) is its leading dimension, not its allocated byte count.
            view = memoryview(bytearray(120)).cast('B', shape=[2, 60])
            self.assert_code('fit_too_large', parse_fit, view)
        with patch('garage.importers.fit.MAX_FRAMES', 1):
            self.assert_code('fit_resource_limit', parse_fit, raw)
        with patch('garage.importers.fit.MAX_SESSIONS', 1):
            self.assert_code('fit_resource_limit', parse_fit, activity(session(), session()))

    def test_stream_io_error_safe(self):
        stream = SimpleNamespace(read=lambda count: (_ for _ in ()).throw(OSError('private path or token')))
        self.assert_code('fit_read_error', parse_fit, stream)


class FitImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = get_user_model().objects.create_user('fit-owner')
        cls.other = get_user_model().objects.create_user('fit-other')
        cls.bike = create_inventory(cls.owner, Bike, name='Synthetic Bike')

    def test_same_hash_session_idempotent_unknown_bike_provenance(self):
        first = import_fit(self.owner, activity())
        source = ActivitySource.objects.get()
        stamp = source.observations_updated_at
        repeated = import_fit(self.owner, activity())
        self.assertEqual(first, repeated)
        self.assertEqual(Ride.objects.count(), 1)
        self.assertEqual(ActivitySource.objects.count(), 1)
        source.refresh_from_db()
        self.assertEqual(source.observations_updated_at, stamp)
        row = Ride.objects.get()
        self.assertIsNone(row.bike_id)
        self.assertTrue(first.sessions[0].pending_bike)
        self.assertEqual(row.field_provenance['distance_m']['kind'], 'fit')
        self.assertEqual(row.field_provenance['moving_time_s']['kind'], 'unknown')
        self.assertEqual(source.parser_version, PARSER_VERSION)

    def test_same_file_two_owners_and_manual_null_override_preserved(self):
        result = import_fit(self.owner, activity())
        ride_id = result.sessions[0].ride_id
        corrected = correct_ride(self.owner, ride_id, distance_m=None, timer_time_s=Decimal('99.123'), bike=self.bike.pk)
        provenance = corrected.field_provenance
        import_fit(self.owner, activity())
        import_fit(self.other, activity())
        ride = Ride.objects.get(pk=ride_id)
        self.assertIsNone(ride.distance_m)
        self.assertEqual(ride.timer_time_s, Decimal('99.123'))
        self.assertEqual(ride.bike_id, self.bike.pk)
        self.assertEqual(ride.field_provenance['distance_m'], provenance['distance_m'])
        self.assertEqual(Ride.objects.count(), 2)
        self.assertEqual(ActivitySource.objects.filter(owner=self.other).count(), 1)

    def test_bad_file_never_creates_rows_or_jobs(self):
        for encoded in (activity()[:-1], activity() + b'x', activity(session(), session()), activity(session(sport=1))):
            with self.assertRaises(ValidationError):
                import_fit(self.owner, encoded)
        self.assertFalse(Ride.objects.exists())
        self.assertFalse(ActivitySource.objects.exists())
        self.assertFalse(ImportRun.objects.exists())

    def test_second_session_failure_rolls_back_everything(self):
        from .services.rides import import_fit_session
        calls = []
        def failure(actor, **kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise ValidationError('synthetic failure')
            return import_fit_session(actor, **kwargs)
        with patch('garage.services.rides.import_fit_session', side_effect=failure):
            with self.assertRaises(ValidationError):
                import_fit(self.owner, activity(session(), session(start=1_100_010_000)), session_indices=[0, 1])
        self.assertFalse(Ride.objects.exists())
        self.assertFalse(ActivitySource.objects.exists())

    def test_selected_mixed_sport_sessions_original_index_reimport(self):
        raw = activity(session(sport=1), session(start=1_100_010_000))
        result = import_fit(self.owner, raw, session_indices=[1])
        self.assertEqual(result.sessions[0].session_index, 1)
        self.assertEqual(ActivitySource.objects.get().session_index, 1)
        self.assertEqual(import_fit(self.owner, raw, session_indices=[1]), result)
        self.assertEqual(Ride.objects.count(), 1)

    def test_foreign_import_run_and_inactive_actor_reject_before_read(self):
        run = create_import_run(self.other)
        with self.assertRaises(InventoryNotFound) as caught:
            import_fit(self.owner, activity(), import_run_id=run.pk)
        self.assertEqual(getattr(caught.exception, 'code', None), 'resource_not_found')
        self.assertFalse(Ride.objects.exists())
        stream = SimpleNamespace(read=lambda count: self.fail('unauthorized stream read'))
        self.owner.is_active = False
        with self.assertRaises(PermissionDenied):
            import_fit(self.owner, stream)

    def test_owned_run_link_and_withdrawn_requires_explicit_reactivation(self):
        run = create_import_run(self.owner)
        result = import_fit(self.owner, activity(), import_run_id=run.pk)
        source = ActivitySource.objects.get()
        self.assertEqual(source.import_run_id, run.pk)
        withdraw_source(self.owner, source.pk)
        with self.assertRaises(ValidationError):
            import_fit(self.owner, activity())
        repeat = import_fit(self.owner, activity(), reactivate=True)
        self.assertEqual(repeat.sessions[0].ride_id, result.sessions[0].ride_id)
        self.assertEqual(ActivitySource.objects.count(), 1)
