"""Bounded FIT activity decoding and authorized, all-or-nothing import.

fitdecode 0.11.0 (MIT; dependency distribution includes its license) decodes the
binary framing/profile. Never use its scaled float values for Garage metrics.
Only native Session fields listed below leave this module (since garage-030 phase 3
also elevation gain, power and work); records, laps,
developer fields, GPS, health, equipment identifiers and raw files are discarded.
Multi-session files require explicit original Session indices. Non-cycling
sessions may be inspected as unsupported and must not be selected for import.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from io import BytesIO
import struct
from uuid import UUID

import fitdecode
from django.core.exceptions import ValidationError

from garage.ride_values import plausible
from garage.validators import exact_usage_value

MAX_FILE_BYTES = 15 * 1024 * 1024
MAX_FRAMES = 500_000
MAX_SESSIONS = 100
# -m2: session elevation, power and work (garage-030 phase 3). Re-importing a file
# imported by an older parser refreshes its source with the new observations.
PARSER_VERSION = 'fitdecode-0.11.0-m2'
FIT_EPOCH = datetime(1989, 12, 31, tzinfo=timezone.utc)
CORE_FIELDS = {2: 'started_at', 5: 'sport_type', 7: 'elapsed_time_s',
               8: 'timer_time_s', 9: 'distance_m', 59: 'moving_time_s'}
# avg_power (W), max_power (W), total_ascent (m), normalized_power (W), total_work (J).
OPTIONAL_FIELDS = {20: 'average_power_w', 21: 'max_power_w', 22: 'elevation_gain_m', 34: 'weighted_power_w', 48: 'energy_kj'}
NATIVE_FIELDS = {**CORE_FIELDS, **OPTIONAL_FIELDS}
# Optional observations (garage-030 phase 3): repeated, malformed or outside their
# plausible range they are unknown, never an error. A file that imported before
# this phase (when these fields were ignored) still imports.
PLAUSIBILITY_CHECKED = ('elevation_gain_m', 'average_power_w', 'max_power_w', 'weighted_power_w', 'energy_kj')
OBSERVATION_FIELDS = ('started_at', 'sport_type', 'distance_m', 'moving_time_s', 'timer_time_s', 'elapsed_time_s',
                      *PLAUSIBILITY_CHECKED)


def fail(code, message):
    raise ValidationError(message, code=code)


@dataclass(frozen=True)
class FitSession:
    session_index: int
    started_at: datetime
    sport_type: str
    distance_m: Decimal | None
    moving_time_s: Decimal | None
    timer_time_s: Decimal | None
    elapsed_time_s: Decimal | None
    elevation_gain_m: Decimal | None = None
    average_power_w: Decimal | None = None
    max_power_w: Decimal | None = None
    weighted_power_w: Decimal | None = None
    energy_kj: Decimal | None = None

    def observations(self):
        return {key: getattr(self, key) for key in OBSERVATION_FIELDS}


@dataclass(frozen=True)
class ParsedFit:
    file_hash: str
    sessions: tuple[FitSession, ...]
    parser_version: str = PARSER_VERSION


@dataclass(frozen=True)
class ImportedSession:
    session_index: int
    ride_id: UUID
    source_id: UUID
    pending_bike: bool


@dataclass(frozen=True)
class FitImportResult:
    file_hash: str
    sessions: tuple[ImportedSession, ...]


def read_bounded(source):
    """Bytes or a binary stream, never a filesystem path; leave caller stream open."""
    if isinstance(source, bytes):
        data = source
    elif isinstance(source, (bytearray, memoryview)):
        source_size = source.nbytes if isinstance(source, memoryview) else len(source)
        if source_size > MAX_FILE_BYTES:
            fail('fit_too_large', 'El FIT supera el límite de 15 MiB.')
        data = bytes(source)
    elif callable(getattr(source, 'read', None)):
        chunks, size = [], 0
        try:
            while True:
                chunk = source.read(min(65536, MAX_FILE_BYTES + 1 - size))
                if not isinstance(chunk, bytes):
                    fail('fit_invalid_input', 'Se necesita un flujo binario FIT.')
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    fail('fit_too_large', 'El FIT supera el límite de 15 MiB.')
                chunks.append(chunk)
        except (OSError, ValueError):
            fail('fit_read_error', 'No se pudo leer el archivo FIT.')
        data = b''.join(chunks)
    else:
        fail('fit_invalid_input', 'Aporta bytes o un flujo binario FIT, no una ruta.')
    if len(data) > MAX_FILE_BYTES:
        fail('fit_too_large', 'El FIT supera el límite de 15 MiB.')
    return data


def native_fields(message):
    """Session fields by number. A repeated core field rejects the file; a repeated optional one is unknown."""
    fields, repeated = {}, set()
    for field in message.fields:
        if field.field is None or field.field.field_type == 'devfield':
            continue
        if field.def_num in NATIVE_FIELDS:
            if field.def_num in fields:
                if field.def_num in OPTIONAL_FIELDS:
                    repeated.add(field.def_num)
                    continue
                fail('fit_duplicate_field', 'La sesión FIT contiene un campo nativo duplicado.')
            fields[field.def_num] = field
    for number in repeated:
        del fields[number]
    return fields


def decimal_metric(field):
    """Convert source integers through profile scale/offset without float rounding."""
    if field is None or field.raw_value is None:
        return None
    if type(field.raw_value) is not int:
        fail('fit_invalid_metric', 'Una métrica FIT debe contener un entero nativo válido.')
    try:
        scale = Decimal(str(field.field.scale)) if field.field.scale is not None else Decimal(1)
        offset = Decimal(str(field.field.offset)) if field.field.offset is not None else Decimal(0)
        if not scale.is_finite() or scale <= 0 or not offset.is_finite():
            fail('fit_invalid_metric', 'La escala FIT no es válida.')
        with localcontext() as context:
            context.prec = 50
            value = Decimal(field.raw_value) / scale - offset
        return exact_usage_value(value)
    except (InvalidOperation, ZeroDivisionError, ValueError, TypeError):
        fail('fit_invalid_metric', 'La métrica FIT no se puede normalizar exactamente.')


def optional_metric(field, divisor=1):
    """An optional observation: a non-integer, array or unnormalizable value is unknown (None), never an error."""
    try:
        value = decimal_metric(field)
        return value if value is None or divisor == 1 else exact_usage_value(value / divisor)
    except ValidationError:
        return None


def session_from_message(message, index):
    fields = native_fields(message)
    start = fields.get(2)
    raw_start = start.raw_value if start else None
    # FIT values below this threshold are relative system timestamps, not UTC.
    if type(raw_start) is not int or not 0x10000000 <= raw_start < 0xFFFFFFFF:
        fail('fit_start_required', 'Cada sesión necesita un inicio UTC absoluto válido.')
    try:
        started = FIT_EPOCH + timedelta(seconds=raw_start)
    except (OverflowError, ValueError):
        fail('fit_invalid_start', 'El inicio FIT no es representable.')
    sport = fields.get(5)
    raw_sport = sport.raw_value if sport else None
    sport_type = 'cycling' if type(raw_sport) is int and raw_sport == 2 else 'unsupported'
    values = {name: decimal_metric(fields.get(number)) for number, name in CORE_FIELDS.items()
              if name not in ('started_at', 'sport_type')}
    # total_work is whole joules: kilojoules with exactly three decimals.
    values.update({name: optional_metric(fields.get(number), 1000 if name == 'energy_kj' else 1)
                   for number, name in OPTIONAL_FIELDS.items()})
    for name in PLAUSIBILITY_CHECKED:
        values[name] = plausible(name, values[name])
    return FitSession(index, started, sport_type, **values)


def decoded_frames(reader):
    """Translate decoder failures only while advancing its binary iterator.

    fitdecode 0.11.0 asserts that each record fits inside the declared body;
    malformed internal records with a recomputed CRC can reach that assertion.
    Keep this boundary away from our field normalization and service code.
    """
    iterator = iter(reader)
    while True:
        try:
            frame = next(iterator)
        except StopIteration:
            return
        except (fitdecode.FitError, EOFError, struct.error, UnicodeError,
                ValueError, OverflowError, AssertionError):
            # Library messages may contain private record fields; do not expose them.
            fail('fit_decode_error', 'El FIT está corrupto o no se puede decodificar íntegramente.')
        yield frame


def parse_fit(source):
    data = read_bounded(source)
    if len(data) < 14 or data[0] not in (12, 14) or data[8:12] != b'.FIT':
        fail('fit_invalid_header', 'No es un contenedor FIT válido.')
    header_size = data[0]
    payload_size = struct.unpack_from('<I', data, 4)[0]
    if len(data) != header_size + payload_size + 2:
        fail('fit_invalid_size', 'El FIT está incompleto o contiene datos adicionales.')
    sessions, activity = [], False
    with fitdecode.FitReader(BytesIO(data), processor=None,
            check_crc=fitdecode.CrcCheck.RAISE, error_handling=fitdecode.ErrorHandling.RAISE,
            keep_raw_chunks=True) as reader:
        for count, frame in enumerate(decoded_frames(reader), 1):
            if count > MAX_FRAMES:
                fail('fit_resource_limit', 'El FIT contiene demasiados mensajes.')
            if isinstance(frame, (fitdecode.FitDefinitionMessage, fitdecode.FitDataMessage)):
                # Enforce the binary body boundary independently of library asserts
                # (Python -O disables them). Chunks are transient and never returned.
                chunk = frame.chunk
                if chunk.offset < header_size or chunk.offset + len(chunk.bytes) > header_size + payload_size:
                    fail('fit_decode_error', 'Un mensaje FIT atraviesa el final del cuerpo declarado.')
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.global_mesg_num == 0:
                type_fields = [field for field in frame.fields if field.def_num == 0
                               and field.field is not None and field.field.field_type != 'devfield']
                file_type = type_fields[0].raw_value if len(type_fields) == 1 else None
                if file_type != 4:
                    fail('fit_not_activity', 'Solo se admiten archivos FIT de actividad.')
                activity = True
            elif frame.global_mesg_num == 18:
                if len(sessions) >= MAX_SESSIONS:
                    fail('fit_resource_limit', 'El FIT contiene demasiadas sesiones.')
                sessions.append(session_from_message(frame, len(sessions)))
    if not activity:
        fail('fit_not_activity', 'Falta la declaración FIT de archivo de actividad.')
    if not sessions:
        fail('fit_no_sessions', 'El FIT no contiene sesiones de actividad.')
    return ParsedFit(sha256(data).hexdigest(), tuple(sessions))


def select_sessions(parsed, session_indices=None):
    if session_indices is None:
        if len(parsed.sessions) != 1:
            fail('fit_selection_required', 'Selecciona explícitamente las sesiones del FIT multisesión.')
        indices = (0,)
    else:
        if not isinstance(session_indices, (list, tuple)) or not session_indices:
            fail('fit_invalid_selection', 'La selección de sesiones debe ser una lista no vacía de índices.')
        if any(type(index) is not int or index < 0 or index >= len(parsed.sessions) for index in session_indices):
            fail('fit_invalid_selection', 'La selección contiene un índice de sesión inválido.')
        if len(set(session_indices)) != len(session_indices):
            fail('fit_invalid_selection', 'No repitas índices de sesión.')
        indices = tuple(sorted(session_indices))
    selected = tuple(parsed.sessions[index] for index in indices)
    if any(session.sport_type != 'cycling' for session in selected):
        fail('fit_unsupported_sport', 'Solo se pueden importar sesiones identificadas explícitamente como ciclismo.')
    return selected


def import_fit(actor, source, *, session_indices=None, import_run_id=None, reactivate=False):
    """Authenticate before reading; validate whole file before any database writes.

    No job is created here. A caller may supply its owned run. UI/background job
    lifecycle belongs to the next delivery. A withdrawn source requires explicit
    reactivation; manual corrections (including NULL) are resolved by services.
    """
    from django.db import transaction
    from garage.services.ownership import require_actor
    from garage.services.rides import import_fit_session
    owner = require_actor(actor)
    parsed = parse_fit(source)
    selected = select_sessions(parsed, session_indices)
    imported = []
    with transaction.atomic():
        for session in selected:
            ride, activity_source = import_fit_session(owner, file_hash=parsed.file_hash,
                session_index=session.session_index, parser_version=parsed.parser_version,
                observations=session.observations(), import_run_id=import_run_id, reactivate=reactivate)
            imported.append(ImportedSession(session.session_index, ride.pk, activity_source.pk, ride.bike_id is None))
    return FitImportResult(parsed.file_hash, tuple(imported))
