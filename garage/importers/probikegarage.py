"""ProBikeGarage dump -> pure Garage import plan (garage-043).

The dump is the JSON its owner saved from api.probikegarage.com with GET
requests only (format «probikegarage-dump», version 2; contract in
docs/garage-data-sources.md). This module reads and validates it completely,
resolves the null sentinel (0001-01-01T00:00:00Z) and the installation
«mounted since always», and maps everything to a plan of Garage rows without
any database access. garage.services.probikegarage_import compares the plan
with the owner's Garage and writes it through the domain services.

Rides are only read to resolve «since always» and to verify the result: Garage
downloads them from Strava (garage-030), never from this copy. Nothing here
logs: names and notes are personal data. Messages are Spanish because they are
the command's report, one per table and row (id and name).
"""
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
import json
import re
import unicodedata

from django.core.exceptions import ValidationError

from garage.icons import ICON_KEYS
from garage.models import GEAR_ID, Bike, Category, Item, ServiceType
from garage.services.categories import _canonical
from garage.services.lifespan import LIFE_TYPE
from garage.validators import MAX_USAGE_VALUE, exact_usage_value

FORMAT = "probikegarage-dump"
VERSION = 2
MAX_BYTES = 20 * 1024 * 1024
UTC = dt_timezone.utc
SINCE_ALWAYS_NOTE = "Montado desde el principio en ProBikeGarage (fecha exacta desconocida)"
BASELINE_SOURCE = "ProBikeGarage (uso inicial)"
NAME_MAX = Item._meta.get_field("name").max_length
BIKE_TEXT_MAX = Bike._meta.get_field("brand").max_length
CATEGORY_MAX = Category._meta.get_field("name").max_length
TYPE_MAX = ServiceType._meta.get_field("name").max_length
INTEGER_MAX = 2147483647
LIFE_KEY = _canonical(LIFE_TYPE)

# Interval type -> MaintenanceRule threshold (metres, seconds, whole days, rides, metres of elevation).
INTERVAL_FIELDS = {"distance": "distance_m", "moving-time": "moving_time_s", "elapsed-time": "calendar_days",
                   "rides": "ride_count", "elevation-gain": "elevation_gain_m"}
# Initial usage -> UsageBaseline metric. Elevation has no reading (UsageBaseline has no such metric).
BASELINE_METRICS = (("distance", "distance_m"), ("moving_time", "moving_time_s"), ("rides", "ride_count"))

# ProBikeGarage type -> (category, icon). Names of the garage-041 starter set where one fits,
# so «Crear las categorías habituales» never duplicates them later.
TYPE_CATEGORIES = {
    "chain": ("Cadena", "chain"),
    "cassette": ("Casete", "cassette"),
    "chainrings": ("Platos", "chainring"),
    "cranks": ("Bielas", "crank"),
    "bottom-bracket": ("Pedalier", "bottom_bracket"),
    "front-derailleur": ("Desviador delantero", "derailleur"),
    "rear-derailleur": ("Desviador trasero", "derailleur"),
    "shifter": ("Manetas de cambio", "shifter"),
    "cable": ("Cables y fundas", "cable"),
    "wheel": ("Rueda", "wheel"),
    "rim": ("Llanta", "rim"),
    "spoke": ("Radios", "spoke"),
    "hub": ("Buje", "hub"),
    "tyre": ("Cubierta", "tire"),
    "inner-tube": ("Cámara", "tube"),
    "sealant": ("Líquido sellante", "sealant"),
    "insert": ("Insertos tubeless", "tire"),
    "brake": ("Frenos", "caliper"),
    "brake-pads": ("Pastillas", "brake"),
    "brake-rotor": ("Discos", "disc"),
    "brake-caliper": ("Pinzas", "caliper"),
    "brake-lever": ("Manetas de freno", "brake_lever"),
    "fork": ("Horquilla de suspensión", "suspension_fork"),
    "shock": ("Amortiguador", "shock"),
    "headset": ("Dirección", "headset"),
    "stem": ("Potencia", "stem"),
    "handlebar": ("Manillar", "handlebar"),
    "grips": ("Puños o cinta", "grips"),
    "seat-post": ("Tija", "seatpost"),
    "saddle": ("Sillín", "saddle"),
    "pedals": ("Pedales", "pedal"),
    "bearings": ("Rodamientos", "part"),
    "frame": ("Cuadro", "bike"),
    "chainguide": ("Guía de cadena", "part"),
    "light": ("Luces", "light"),
    "battery": ("Batería", "battery"),
    "computer": ("Ciclocomputador", "computer"),
    "helmet": ("Casco", "helmet"),
    "shoes": ("Zapatillas", "shoe"),
}
INSERTS = TYPE_CATEGORIES["insert"]
# Type «other»: the first keyword that starts a word of the name (no accents, lower case) decides.
OTHER_KEYWORDS = (("cala", ("Calas", "cleat")), ("roldana", ("Roldanas", "derailleur")), ("nube", INSERTS), ("insert", INSERTS))
FALLBACK_CATEGORY = ("Otros", "part")
assert all(icon in ICON_KEYS for _, icon in (*TYPE_CATEGORIES.values(), FALLBACK_CATEGORY, *(c for _, c in OTHER_KEYWORDS)))


class DumpError(Exception):
    """The file cannot be read as JSON (size, encoding or syntax); the message is Spanish."""


def _reject_constant(name):
    raise ValueError(f"JSON constant {name} is not a number")


def loads_dump(text):
    """Decimal numbers (never floats) and no NaN/Infinity, as Garage's other importers."""
    try:
        return json.loads(text, parse_float=Decimal, parse_constant=_reject_constant)
    except ValueError:
        raise DumpError("El volcado no es JSON válido.") from None


def load_dump(path):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)
    except OSError as error:
        raise DumpError(f"No se puede leer el volcado ({error.strerror or 'error de lectura'}).") from None
    if len(raw) > MAX_BYTES:
        raise DumpError("El volcado supera los 20 MB admitidos.")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DumpError("El volcado no está codificado en UTF-8.") from None
    return loads_dump(text)


def _plain(text):
    decomposed = unicodedata.normalize("NFKD", str(text or "").lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def category_for(pbg_type, name):
    """(category, icon, known): the Garage category of a ProBikeGarage component type."""
    if pbg_type == "other":
        words = re.findall(r"[a-z0-9]+", _plain(name))
        for keyword, category in OTHER_KEYWORDS:
            if any(word.startswith(keyword) for word in words):
                return (*category, True)
        return (*FALLBACK_CATEGORY, True)
    if pbg_type in TYPE_CATEGORIES:
        return (*TYPE_CATEGORIES[pbg_type], True)
    return (*FALLBACK_CATEGORY, False)


def _parse_instant(value):
    """(aware UTC instant or None, problem or None). The year-1 sentinel and '' are None."""
    if value is None or value == "":
        return None, None
    if not isinstance(value, str):
        return None, "no es un instante ISO 8601"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, "no es un instante ISO 8601"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None, "es un instante sin zona horaria"
    if parsed.year == 1:
        return None, "sentinel"
    try:
        return parsed.astimezone(UTC), None
    except (OverflowError, ValueError):
        return None, "está fuera del rango admitido"


def _decimal(value):
    """Decimal or None for a JSON number; bools, text and non-finite values are not numbers."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        value = Decimal(repr(value))
    if isinstance(value, Decimal) and value.is_finite():
        return value
    return None


def _when(instant):
    return instant.strftime("%d/%m/%Y %H:%M UTC")


@dataclass(frozen=True)
class Issue:
    table: str
    row_id: str
    name: str
    message: str

    def __str__(self):
        where = self.table
        if self.row_id:
            where += f" {self.row_id}"
        if self.name:
            where += f" «{self.name}»"
        return f"{where}: {self.message}"


@dataclass(frozen=True)
class Usage:
    """ProBikeGarage's own totals (metres, seconds, metres, rides); only the verification reads them."""
    distance: Decimal | None = None
    moving_time: Decimal | None = None
    elevation_gain: Decimal | None = None
    rides: Decimal | None = None


@dataclass(frozen=True)
class PlannedBike:
    pbg_id: str
    name: str
    brand: str
    model: str
    retired_at: datetime | None
    gear_id: str
    gear_name: str
    usage: Usage


@dataclass(frozen=True)
class PlannedItem:
    pbg_id: str
    name: str
    pbg_type: str
    category: str
    notes: str
    retired_at: datetime | None
    first_mount_at: datetime | None
    usage: Usage


@dataclass(frozen=True)
class PlannedInstallation:
    pbg_id: str
    component_id: str
    bike_id: str | None
    parent_id: str | None
    started_at: datetime
    ended_at: datetime | None
    notes: str
    since_always: bool
    depth: int


@dataclass(frozen=True)
class PlannedInterval:
    pbg_id: str
    component_id: str
    title: str
    kind: str
    field: str
    threshold: object  # Decimal for metres/seconds, int for days and rides
    repeat: bool
    next: Decimal | None
    notes: str = ""


@dataclass(frozen=True)
class PlannedRule:
    component_id: str
    service_type: str
    thresholds: tuple  # ((field, value), ...)
    anchor_at: datetime | None
    notes: str
    interval_ids: tuple
    life: bool


@dataclass(frozen=True)
class PlannedEvent:
    service_id: str
    component_id: str | None
    bike_id: str | None
    service_type: str
    performed_at: datetime
    notes: str
    interval_id: str | None


@dataclass(frozen=True)
class PlannedBaseline:
    component_id: str
    metric: str
    cut_at: datetime
    value: Decimal


@dataclass(frozen=True)
class DumpRide:
    strava_id: int
    started_at: datetime
    bike_id: str | None
    gear_id: str
    distance: Decimal | None
    moving_time: Decimal | None
    elevation_gain: Decimal | None


@dataclass(frozen=True)
class Plan:
    exported_at: datetime | None
    bikes: tuple = ()
    items: tuple = ()
    installations: tuple = ()  # bikes first, then nested by depth: a parent always exists before
    intervals: tuple = ()
    rules: tuple = ()
    events: tuple = ()
    baselines: tuple = ()
    rides: tuple = ()
    categories: tuple = ()  # ((name, icon), ...) in first-use order
    service_types: tuple = ()  # names in first-use order, unique without case
    warnings: tuple = ()
    errors: tuple = ()

    @property
    def ok(self):
        return not self.errors


def build_plan(dump):
    """Validate the whole dump and map it to a Plan; never raises for its content."""
    return _Planner(dump).plan()


class _Planner:
    def __init__(self, dump):
        self.dump = dump
        self.errors = []
        self.warnings = []

    # Reporting -----------------------------------------------------------

    def error(self, table, row_id, name, message):
        self.errors.append(Issue(table, row_id, name, message))

    def warn(self, table, row_id, name, message):
        self.warnings.append(Issue(table, row_id, name, message))

    # Field readers ---------------------------------------------------------

    def text(self, where, row, key, *, required=False, max_length=None):
        value = row.get(key)
        if value is None:
            value = ""
        if not isinstance(value, str):
            self.error(*where, f"«{key}» debe ser texto")
            return ""
        value = value.strip()
        if required and not value:
            self.error(*where, f"«{key}» está vacío")
        if max_length is not None and len(value) > max_length:
            self.error(*where, f"«{key}» supera los {max_length} caracteres que admite Garage")
        return value

    def instant(self, where, row, key, *, required=False):
        parsed, problem = _parse_instant(row.get(key))
        if problem == "sentinel":
            if required:
                self.error(*where, f"«{key}» tiene la fecha nula de ProBikeGarage (0001-01-01)")
            return None
        if problem:
            self.error(*where, f"«{key}» {problem}")
            return None
        if parsed is None and required:
            self.error(*where, f"falta «{key}»")
        return parsed

    def references(self, where, row, key, universe, label):
        value = row.get(key)
        if value is None:
            return []
        if not isinstance(value, list):
            self.error(*where, f"«{key}» debe ser una lista")
            return []
        found = []
        for entry in value:
            if not isinstance(entry, str) or entry not in universe:
                self.error(*where, f"referencia rota: «{key}» contiene {entry!r}, que no está en {label}")
            elif entry not in found:
                found.append(entry)
        return found

    def usage(self, where, value, key):
        """Lenient: only the verification reads these totals; a bad value is unknown and warned."""
        if value is None:
            return Usage()
        if not isinstance(value, dict):
            self.warn(*where, f"«{key}» no es un objeto: la verificación no lo comparará")
            return Usage()
        numbers = {}
        for name in ("distance", "moving_time", "elevation_gain", "rides"):
            raw = value.get(name)
            number = _decimal(raw)
            if raw is not None and (number is None or number < 0):
                self.warn(*where, f"«{key}.{name}» no es un número válido: la verificación no lo comparará")
                number = None
            numbers[name] = number
        return Usage(**numbers)

    def rows(self, key, *, required=True):
        value = self.dump.get(key)
        if value is None and not required:
            return []
        if not isinstance(value, list):
            self.error("volcado", "", "", f"falta la lista «{key}»")
            return []
        rows, seen = [], set()
        for index, row in enumerate(value):
            if not isinstance(row, dict):
                self.error(key, f"[{index}]", "", "no es un objeto")
                continue
            row_id = row.get("id")
            if not isinstance(row_id, str) or not row_id.strip():
                self.error(key, f"[{index}]", "", "falta «id»")
                continue
            if row_id in seen:
                self.error(key, row_id, "", "«id» repetido")
                continue
            seen.add(row_id)
            rows.append(row)
        return rows

    # The plan ----------------------------------------------------------------

    def plan(self):
        dump = self.dump
        if not isinstance(dump, dict):
            self.error("volcado", "", "", "no es un objeto JSON")
            return self.result(None)
        if dump.get("format") != FORMAT:
            self.error("volcado", "", "", f"formato {dump.get('format')!r} desconocido: se esperaba «{FORMAT}»")
        version = dump.get("version")
        if isinstance(version, bool) or version != VERSION:
            self.error("volcado", "", "", f"versión {version!r} no admitida: se esperaba {VERSION}")
        if self.errors:
            return self.result(None)
        exported_at = self.instant(("volcado", "", ""), dump, "exported_at", required=True)
        bike_rows = self.rows("bikes")
        component_rows = self.rows("components")
        installation_rows = self.rows("installations")
        service_rows = self.rows("services")
        bikes = self.read_bikes(bike_rows)
        components, intervals = self.read_components(component_rows)
        installations = self.read_installations(installation_rows, bikes, components)
        self.check_current_installations(component_rows, {row["id"] for row in installation_rows}, installations)
        rides = self.read_rides(bikes)
        depth = self.nesting_depth(installations, components)
        self.resolve_since_always(installations, components, rides, depth)
        self.check_overlaps(installations, components)
        self.check_retirements(installations, components, bikes)
        first_mount = {}
        for mount in installations.values():
            if mount["started_at"] is not None:
                current = first_mount.get(mount["component_id"])
                first_mount[mount["component_id"]] = mount["started_at"] if current is None else min(current, mount["started_at"])
        rules = self.plan_rules(components, intervals, first_mount)
        events = self.plan_events(service_rows, bikes, components, intervals, rules)
        baselines = self.plan_baselines(components, first_mount, exported_at, rules)
        if self.errors:
            return self.result(exported_at)
        planned_bikes = tuple(PlannedBike(bid, b["name"], b["brand"], b["model"], b["retired_at"], b["gear_id"], b["gear_name"], b["usage"])
                              for bid, b in bikes.items())
        planned_items = tuple(PlannedItem(cid, c["name"], c["type"], c["category"], c["notes"], c["retired_at"], first_mount.get(cid), c["usage"])
                              for cid, c in components.items())
        mounts = [PlannedInstallation(iid, m["component_id"], m["bike_id"], m["parent_id"], m["started_at"], m["ended_at"],
                                      SINCE_ALWAYS_NOTE if m["since_always"] else "", m["since_always"],
                                      0 if m["bike_id"] else depth[m["component_id"]]) for iid, m in installations.items()]
        mounts.sort(key=lambda m: (m.depth, m.started_at, m.pbg_id))
        categories, seen = [], set()
        for component in components.values():
            key = _canonical(component["category"])
            if key not in seen:
                seen.add(key)
                categories.append((component["category"], component["icon"]))
        types, seen = [], set()
        for name in [rule.service_type for rule in rules] + [event.service_type for event in events]:
            if _canonical(name) not in seen:
                seen.add(_canonical(name))
                types.append(name)
        return Plan(exported_at, planned_bikes, planned_items, tuple(mounts), tuple(intervals.values()), tuple(rules), tuple(events),
                    tuple(baselines), tuple(rides), tuple(categories), tuple(types), tuple(self.warnings), ())

    def result(self, exported_at):
        return Plan(exported_at, warnings=tuple(self.warnings), errors=tuple(self.errors))

    def read_bikes(self, rows):
        bikes, gear = {}, {}
        for row in rows:
            bid, name = row["id"], row.get("name") if isinstance(row.get("name"), str) else ""
            where = ("bikes", bid, name.strip())
            name = self.text(where, row, "name", required=True, max_length=NAME_MAX)
            retired_at = self.instant(where, row, "retired_at")
            strava = row.get("strava_bike")
            gear_id = gear_name = brand = model = ""
            if strava is None:
                self.warn(*where, "no tiene bici de Strava: sus salidas de Strava quedarán sin bici hasta vincularla en Más → Strava")
            elif not isinstance(strava, dict):
                self.error(*where, "«strava_bike» debe ser un objeto")
            else:
                gear_id = strava.get("id") or ""
                if not isinstance(gear_id, str) or (gear_id and not GEAR_ID.regex.search(gear_id)):
                    self.error(*where, f"«strava_bike.id» {gear_id!r} no es un identificador de bici de Strava")
                    gear_id = ""
                elif gear_id in gear:
                    self.error(*where, f"«strava_bike.id» {gear_id} también es de la bici {gear[gear_id]}")
                elif not gear_id:
                    self.warn(*where, "su bici de Strava no tiene id: sus salidas de Strava quedarán sin bici hasta vincularla")
                if gear_id:
                    gear.setdefault(gear_id, bid)
                gear_name = self.text(where, strava, "name")[:NAME_MAX]
                brand = self.text(where, strava, "brand_name", max_length=BIKE_TEXT_MAX)
                model = self.text(where, strava, "model_name", max_length=BIKE_TEXT_MAX)
            if row.get("default") is True:
                self.warn(*where, "era la bici por defecto: Garage no asigna bici por defecto (las salidas la toman de Strava)")
            bikes[bid] = {"name": name, "retired_at": retired_at, "gear_id": gear_id, "gear_name": gear_name, "brand": brand,
                          "model": model, "usage": self.usage(where, row.get("usage"), "usage")}
        return bikes

    def read_components(self, rows):
        components, intervals = {}, {}
        for row in rows:
            cid, raw_name = row["id"], row.get("name")
            where = ("components", cid, raw_name.strip() if isinstance(raw_name, str) else "")
            name = self.text(where, row, "name", required=True, max_length=NAME_MAX)
            pbg_type = self.text(where, row, "type")
            category, icon, known = category_for(pbg_type, name)
            if not known:
                self.warn(*where, f"tipo {pbg_type!r} sin categoría propia: va a «{category}»")
            initial = row.get("initial_usage")
            if initial is not None and not isinstance(initial, dict):
                self.error(*where, "«initial_usage» debe ser un objeto")
                initial = None
            initial_values = {}
            for key in ("distance", "moving_time", "elevation_gain", "rides"):
                raw = (initial or {}).get(key)
                number = _decimal(raw)
                if raw is not None and (number is None or number < 0 or number > MAX_USAGE_VALUE):
                    self.error(*where, f"«initial_usage.{key}» no es un número válido")
                    number = None
                initial_values[key] = number
            component = {"name": name, "type": pbg_type, "category": category, "icon": icon, "notes": self.text(where, row, "notes"),
                         "retired_at": self.instant(where, row, "retired_at"), "initial": initial_values,
                         "usage": self.usage(where, row.get("usage"), "usage"), "intervals": []}
            components[cid] = component
            listed = row.get("service_intervals")
            if listed is None:
                listed = []
            if not isinstance(listed, list):
                self.error(*where, "«service_intervals» debe ser una lista")
                listed = []
            for index, interval in enumerate(listed):
                planned = self.read_interval(where, index, interval, cid, intervals)
                if planned is not None:
                    intervals[planned.pbg_id] = planned
                    component["intervals"].append(planned)
        return components, intervals

    def read_interval(self, owner_where, index, row, component_id, known):
        if not isinstance(row, dict):
            self.error(owner_where[0], owner_where[1], owner_where[2], f"«service_intervals[{index}]» no es un objeto")
            return None
        iid = row.get("id")
        title = row.get("title") if isinstance(row.get("title"), str) else ""
        where = ("service_intervals", iid if isinstance(iid, str) else f"{owner_where[1]}[{index}]", title.strip())
        if not isinstance(iid, str) or not iid.strip():
            self.error(*where, "falta «id»")
            return None
        if iid in known:
            self.error(*where, "«id» repetido")
            return None
        repeat = row.get("repeat")
        if not isinstance(repeat, bool):
            self.error(*where, "«repeat» debe ser true o false")
            return None
        title = self.text(where, row, "title", required=repeat, max_length=TYPE_MAX if repeat else None)
        kind = row.get("type")
        if not isinstance(kind, str) or kind not in INTERVAL_FIELDS:
            self.error(*where, f"tipo de intervalo {kind!r} desconocido")
            return None
        field = INTERVAL_FIELDS[kind]
        value = _decimal(row.get("value"))
        if value is None or value <= 0:
            self.error(*where, f"«value» {row.get('value')!r} debe ser un número mayor que 0")
            return None
        try:
            if field == "calendar_days":
                threshold = max(1, int((value / Decimal(86400)).quantize(Decimal(1), rounding=ROUND_HALF_UP)))
            elif field == "ride_count":
                threshold = int(exact_usage_value(value, metric="ride_count"))
            else:
                threshold = exact_usage_value(value)
        except (ValidationError, InvalidOperation, OverflowError):
            self.error(*where, f"«value» {row.get('value')!r} no cabe en un umbral de Garage")
            return None
        if field in ("calendar_days", "ride_count") and threshold > INTEGER_MAX:
            self.error(*where, f"«value» {row.get('value')!r} no cabe en un umbral de Garage")
            return None
        nxt = row.get("next")
        next_value = _decimal(nxt)
        if nxt is not None and next_value is None:
            self.warn(*where, "«next» no es un número: la verificación no lo comparará")
        if row.get("snooze") not in (None, {}):
            self.warn(*where, "tenía un aplazamiento: no se importa (se puede posponer de nuevo en Garage)")
        return PlannedInterval(iid, component_id, title, kind, field, threshold, repeat, next_value, self.text(where, row, "notes"))

    def read_installations(self, rows, bikes, components):
        mounts = {}
        for row in rows:
            iid = row["id"]
            # Only text can name a row: anything else (a list, a number) is a broken reference, never a TypeError.
            row = {key: (value if key not in ("component_id", "target_id", "bike_id") or value is None or isinstance(value, str) else repr(value))
                   for key, value in row.items()}
            component_id = row.get("component_id")
            component = components.get(component_id) if isinstance(component_id, str) else None
            where = ("installations", iid, component["name"] if component else "")
            errors = len(self.errors)
            if component is None:
                self.error(*where, f"referencia rota: «component_id» {component_id!r} no está en components")
            target_type, target_id = row.get("target_type"), row.get("target_id")
            bike_id = parent_id = None
            if target_type == "bike":
                if target_id not in bikes:
                    self.error(*where, f"referencia rota: «target_id» {target_id!r} no está en bikes")
                bike_id = target_id
            elif target_type == "component":
                if target_id not in components:
                    self.error(*where, f"referencia rota: «target_id» {target_id!r} no está en components")
                elif target_id == component_id:
                    self.error(*where, "un componente no puede montarse dentro de sí mismo")
                parent_id = target_id
            else:
                self.error(*where, f"«target_type» {target_type!r} desconocido: se esperaba bike o component")
            context_bike = row.get("bike_id")
            if context_bike not in (None, "") and context_bike not in bikes:
                self.error(*where, f"referencia rota: «bike_id» {context_bike!r} no está en bikes")
            # The null sentinel (or no date at all) in added_at means «mounted since always».
            since_always = _parse_instant(row.get("added_at")) in ((None, None), (None, "sentinel"))
            started_at = self.instant(where, row, "added_at")
            ended_at = self.instant(where, row, "removed_at")
            if len(self.errors) > errors:
                continue  # reported: nothing else is derived from a broken row
            if any(row.get(key) for key in ("ride_tags", "included_ride_tags", "excluded_ride_tags")):
                self.warn(*where, "tenía etiquetas de salida: no se importan (Garage usa perfiles y excepciones)")
            mounts[iid] = {"component_id": component_id, "bike_id": bike_id, "parent_id": parent_id, "started_at": started_at,
                           "ended_at": ended_at, "since_always": since_always, "name": where[2]}
        return mounts

    def check_current_installations(self, rows, installation_ids, mounts):
        """Only a consistency check: the installations table is what is imported."""
        for row in rows:
            where = ("components", row["id"], row.get("name").strip() if isinstance(row.get("name"), str) else "")
            for entry in self.references(where, row, "current_installations", installation_ids, "installations"):
                mount = mounts.get(entry)
                if mount is not None and mount["component_id"] != row["id"]:
                    self.warn(*where, f"«current_installations» nombra el montaje {entry} de otro componente: se usa installations")

    def read_rides(self, bikes):
        rows = self.dump.get("rides")
        if rows is None:
            return []
        if not isinstance(rows, list):
            self.error("volcado", "", "", "«rides» debe ser una lista")
            return []
        rides, seen = [], set()
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                self.error("rides", f"[{index}]", "", "no es un objeto")
                continue
            strava_id = row.get("strava_id")
            where = ("rides", str(strava_id) if strava_id is not None else f"[{index}]", "")
            if isinstance(strava_id, bool) or not isinstance(strava_id, int) or strava_id <= 0:
                self.error(*where, "«strava_id» debe ser un entero positivo")
                continue
            if strava_id in seen:
                self.error(*where, "«strava_id» repetido")
                continue
            seen.add(strava_id)
            started_at = self.instant(where, row, "started_at", required=True)
            bike = row.get("bike") or ""
            bike_id = None
            if not isinstance(bike, str):
                self.error(*where, "«bike» debe ser texto")
            elif bike:
                owners = [bid for bid in bikes if bid.startswith(bike)]  # the dump keeps the first 8 characters
                if len(owners) != 1:
                    self.error(*where, f"«bike» {bike!r} no identifica una única bici del volcado")
                else:
                    bike_id = owners[0]
            gear_id = row.get("gear_id") or ""
            if not isinstance(gear_id, str):
                gear_id = ""
            if started_at is not None:
                values = {}
                for key in ("distance", "moving_time", "elevation_gain"):
                    number = _decimal(row.get(key))
                    values[key] = number if number is not None and number >= 0 else None
                rides.append(DumpRide(strava_id, started_at, bike_id, gear_id, values["distance"], values["moving_time"],
                                      values["elevation_gain"]))
        rides.sort(key=lambda ride: (ride.started_at, ride.strava_id))
        return rides

    def resolve_since_always(self, mounts, components, rides, depth):
        """«Mounted since always»: the earliest other mount of its bike (or parent) and first ride of that bike.

        Mounts on a bike first, then parts by depth, whatever the order of the dump: a part «since always»
        inside a part that is also «since always» takes its parent's resolved start into account.
        """
        first_ride = {}
        for ride in rides:
            if ride.bike_id and ride.bike_id not in first_ride:
                first_ride[ride.bike_id] = ride.started_at
        pending = sorted((iid for iid, mount in mounts.items() if mount["since_always"]),
                         key=lambda iid: (0 if mounts[iid]["bike_id"] else depth.get(mounts[iid]["component_id"], 0) + 1, iid))
        for iid in pending:
            mount = mounts[iid]
            where = ("installations", iid, mount["name"])
            if mount["bike_id"]:
                candidates = [other["started_at"] for other_id, other in mounts.items() if other_id != iid
                              and other["bike_id"] == mount["bike_id"] and other["started_at"] is not None]
                if mount["bike_id"] in first_ride:
                    candidates.append(first_ride[mount["bike_id"]])
                place = "de la bici"
            else:
                parent = mount["parent_id"]
                candidates = [other["started_at"] for other_id, other in mounts.items() if other_id != iid
                              and other["started_at"] is not None and (other["component_id"] == parent or other["parent_id"] == parent)]
                place = "de la pieza que lo contiene"
            if not candidates:
                self.error(*where, f"montado «desde siempre» (fecha nula) sin ningún otro montaje ni salida {place} de la que tomar la fecha")
                continue
            mount["started_at"] = min(candidates)
            self.warn(*where, f"montado «desde siempre» en ProBikeGarage: en Garage desde el {_when(mount['started_at'])} "
                              f"(lo más antiguo {place}), con una nota")
        for iid, mount in mounts.items():
            if mount["started_at"] is not None and mount["ended_at"] is not None and mount["ended_at"] <= mount["started_at"]:
                self.error("installations", iid, mount["name"], "el montaje termina antes de empezar (o en el mismo instante)")

    def check_overlaps(self, mounts, components):
        by_component = {}
        for iid, mount in mounts.items():
            if mount["started_at"] is not None:
                by_component.setdefault(mount["component_id"], []).append((mount["started_at"], iid, mount["ended_at"]))
        for component_id, periods in by_component.items():
            periods.sort(key=lambda period: (period[0], period[1]))
            for (start, first, end), (next_start, second, _) in zip(periods, periods[1:]):
                if end is None or end > next_start:
                    name = components[component_id]["name"] if component_id in components else ""
                    self.error("installations", second, name, f"se solapa con el montaje {first} del mismo componente")

    def nesting_depth(self, mounts, components):
        """Depth of each component as a part (0: never inside another); a static cycle is an error."""
        parents = {}
        for mount in mounts.values():
            if mount["parent_id"]:
                parents.setdefault(mount["component_id"], set()).add(mount["parent_id"])
        depth, visiting = {}, set()

        def visit(component_id, path):
            if component_id in depth:
                return depth[component_id]
            if component_id in visiting:
                name = components[component_id]["name"] if component_id in components else ""
                self.error("installations", "", name, "los montajes anidados forman un ciclo (" + " → ".join(path + [component_id]) + ")")
                depth[component_id] = 0
                return 0
            visiting.add(component_id)
            value = 1 + max((visit(parent, path + [component_id]) for parent in sorted(parents.get(component_id, ()))), default=-1)
            visiting.discard(component_id)
            depth[component_id] = value
            return value
        for component_id in sorted(set(parents) | {m["component_id"] for m in mounts.values()}):
            visit(component_id, [])
        return depth

    def check_retirements(self, mounts, components, bikes):
        for iid, mount in mounts.items():
            start, end = mount["started_at"], mount["ended_at"]
            if start is None:
                continue
            owners = [("componente", components.get(mount["component_id"]))]
            if mount["parent_id"]:
                owners.append(("pieza que lo contiene", components.get(mount["parent_id"])))
            if mount["bike_id"]:
                owners.append(("bici", bikes.get(mount["bike_id"])))
            for label, resource in owners:
                retired = resource and resource["retired_at"]
                if not retired:
                    continue
                if start >= retired or (end is not None and end > retired):
                    self.error("installations", iid, mount["name"], f"el montaje sigue después de la retirada de su {label} ({_when(retired)})")
                elif end is None:
                    self.warn("installations", iid, mount["name"], f"sigue abierto: se cerrará al retirar su {label} ({_when(retired)})")

    def plan_rules(self, components, intervals, first_mount):
        rules = []
        for cid, component in components.items():
            where = ("components", cid, component["name"])
            anchor = first_mount.get(cid)
            repeat_titles = {}
            life, life_ids, life_notes = {}, [], []
            for interval in component["intervals"]:
                notes = interval.notes
                if interval.repeat:
                    key = _canonical(interval.title)
                    if key in repeat_titles:
                        self.error("service_intervals", interval.pbg_id, interval.title,
                                   f"otro intervalo repetible de este componente ({repeat_titles[key]}) tiene el mismo título")
                        continue
                    repeat_titles[key] = interval.pbg_id
                    if key == LIFE_KEY:
                        self.warn("service_intervals", interval.pbg_id, interval.title, f"Garage tratará «{LIFE_TYPE}» como la vida útil de la pieza")
                    rules.append(PlannedRule(cid, interval.title, ((interval.field, interval.threshold),), anchor, notes, (interval.pbg_id,), False))
                    continue
                life_ids.append(interval.pbg_id)
                if notes:
                    life_notes.append(notes)
                if interval.field in life:
                    self.warn("service_intervals", interval.pbg_id, interval.title,
                              "otra vida útil de este componente ya fija ese umbral: se conserva el primero")
                else:
                    life[interval.field] = interval.threshold
            if life_ids:
                if LIFE_KEY in repeat_titles:
                    self.error(*where, f"tiene un intervalo repetible «{LIFE_TYPE}» y una vida útil: Garage sólo admite una regla de ese tipo")
                    continue
                rules.append(PlannedRule(cid, LIFE_TYPE, tuple(life.items()), anchor, "\n".join(life_notes), tuple(life_ids), True))
        return rules

    def plan_events(self, rows, bikes, components, intervals, rules):
        rule_types = {}
        for rule in rules:
            rule_types.setdefault(rule.component_id, set()).add(_canonical(rule.service_type))
        events = []
        for row in rows:
            sid = row["id"]
            title = row.get("title") if isinstance(row.get("title"), str) and row.get("title").strip() else row.get("name")
            title = title.strip() if isinstance(title, str) else ""
            where = ("services", sid, title)
            if not title:
                self.error(*where, "falta «title»")
            performed_at = self.instant(where, row, "serviced_at", required=True)
            notes = self.text(where, row, "notes")
            target_type, target_id = row.get("target_type"), row.get("target_id")
            if not isinstance(target_id, str):
                target_id = repr(target_id)
            universe = {"service_interval": intervals, "component": components, "bike": bikes}.get(target_type) \
                if isinstance(target_type, str) else None
            if universe is None:
                self.error(*where, f"«target_type» {target_type!r} desconocido")
            elif target_id not in universe:
                self.error(*where, f"referencia rota: «target_id» {target_id!r} no está en {target_type}s")
            self.references(where, row, "bikes_ids", bikes, "bikes")
            parts = self.references(where, row, "components_ids", components, "components")
            parts += [c for c in self.references(where, row, "target_components_ids", components, "components") if c not in parts]
            listed = self.references(where, row, "service_intervals_ids", intervals, "service_intervals")
            listed += [i for i in self.references(where, row, "target_service_intervals_ids", intervals, "service_intervals") if i not in listed]
            if target_type == "service_interval" and target_id in intervals and target_id not in listed:
                listed.append(target_id)  # the interval it was registered for, even when the dump does not list it again
            if not parts and target_type == "component" and target_id in components:
                parts = [target_id]
            if not parts and target_type == "service_interval" and target_id in intervals:
                parts = [intervals[target_id].component_id]
            for interval_id in listed:
                if intervals[interval_id].component_id not in parts:
                    self.error(*where, f"el intervalo {interval_id} es de un componente que no está en la intervención")
            if performed_at is None or not title:
                continue
            if len(title) > TYPE_MAX and (not parts or any(all(intervals[i].component_id != c for i in listed) for c in parts)):
                self.error(*where, f"«title» supera los {TYPE_MAX} caracteres que admite un tipo de intervención")
                continue
            if not parts:
                if target_type == "bike" and target_id in bikes:
                    events.append(PlannedEvent(sid, None, target_id, title, performed_at, notes, None))
                elif universe is not None:
                    self.error(*where, "no tiene ningún componente ni bici a la que aplicarse")
                continue
            for component_id in parts:
                mine = [intervals[i] for i in listed if intervals[i].component_id == component_id]
                if not mine:
                    if _canonical(title) in rule_types.get(component_id, ()):
                        self.warn(*where, f"no marcaba ningún intervalo en «{components[component_id]['name']}»: en Garage "
                                          f"reinicia su regla «{title}» (mismo tipo, regla general de las intervenciones)")
                    events.append(PlannedEvent(sid, component_id, None, title, performed_at, notes, None))
                    continue
                kinds = set()
                for interval in mine:
                    kind = interval.title if interval.repeat else LIFE_TYPE
                    if _canonical(kind) in kinds:
                        continue  # two «Max life» of one part are one useful life (D2): one «Sustitución»
                    kinds.add(_canonical(kind))
                    text = notes
                    if _canonical(title) != _canonical(kind):
                        text = f"{title.rstrip('.')}. {notes}".rstrip() if notes else f"{title.rstrip('.')}."
                    events.append(PlannedEvent(sid, component_id, None, kind, performed_at, text, interval.pbg_id))
        return events

    def plan_baselines(self, components, first_mount, exported_at, rules):
        baselines = []
        with_life = {rule.component_id for rule in rules if rule.life}
        for cid, component in components.items():
            initial = component["initial"]
            where = ("components", cid, component["name"])
            wanted = [(metric, initial[key]) for key, metric in BASELINE_METRICS if initial[key] is not None and initial[key] > 0]
            if initial["elevation_gain"] is not None and initial["elevation_gain"] > 0:
                self.warn(*where, f"el desnivel inicial ({initial['elevation_gain']} m) no se guarda: las lecturas de Garage no admiten desnivel")
            if not wanted:
                continue
            if cid in with_life:
                # Rules count rides since their reference, never lifetime readings (domain §14).
                self.warn(*where, "tiene uso inicial y vida útil: la vida útil de Garage no suma la lectura inicial estimada "
                                  "(cuenta las salidas desde su referencia)")
            cut = first_mount.get(cid)
            if cut is None:
                if exported_at is None:
                    continue
                cut = exported_at
                self.warn(*where, "uso inicial de una pieza nunca montada: la lectura se fecha en el instante del volcado")
            for metric, value in wanted:
                try:
                    value = exact_usage_value(value, metric=metric)
                except ValidationError:
                    self.error(*where, f"el uso inicial ({metric}) no es un valor exacto admitido")
                    continue
                baselines.append(PlannedBaseline(cid, metric, cut, value))
        return baselines
