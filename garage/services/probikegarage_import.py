"""Import a ProBikeGarage dump into an empty Garage, and compare Garage with it (garage-043).

preview() reads the owner's Garage and returns the plan and its report; it
never writes. apply() writes the plan in one transaction under the owner lock,
only through the domain services (create_inventory, ensure_gear/link_gear,
create_installation, save_maintenance, set_lifespan, record_baseline,
retire_inventory) and ends with rebuild_usage(). Every service takes the owner
lock again inside this transaction (reentrant), so any error rolls back the
whole import. It only runs on a Garage without bikes or items (one use, no
--force). verify() compares the owner's Garage with the dump and writes nothing.

Rides are not imported: Garage downloads them from Strava (garage-030), and the
linked StravaGear assigns each one to its bike. The garage logger only receives
counts; names and notes are personal data and appear only in the report.
"""
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone as dt_timezone, tzinfo
from decimal import Decimal
import logging
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Min, Sum

from garage.importers.probikegarage import BASELINE_SOURCE, LIFE_KEY, build_plan
from garage.models import ActivitySource, Bike, Category, Installation, Item, ItemUsage, MaintenanceRule, Ride, ServiceEvent, ServiceType
from .baselines import record_baseline
from .categories import _canonical
from .installations import create_installation
from .lifespan import LIFE_TYPE, _life_type, set_lifespan
from .maintenance import save_maintenance
from .maintenance_due import _elapsed_days, maintenance_due
from .ownership import InventoryWriteError, _lock_owner, create_inventory, require_actor, retire_inventory
from .strava_sources import ensure_gear, link_gear
from .usage import rebuild_usage, summarize_item_usage

logger = logging.getLogger(__name__)
UTC = dt_timezone.utc
MAPPING_FORMAT = "probikegarage-mapping"
LIFE_THRESHOLDS = ("distance_m", "moving_time_s", "calendar_days", "elevation_gain_m")


class ImportRejected(InventoryWriteError):
    """Validation found errors: nothing was written. `report` lists them per table and row."""

    def __init__(self, report):
        super().__init__({"__all__": [str(error) for error in report.errors] or ["La importación no es válida."]})
        self.report = report


class ImportFailed(InventoryWriteError):
    """A domain service refused a row while writing: the whole import was rolled back."""


@dataclass(frozen=True)
class OwnerState:
    bikes: int
    items: int
    categories: dict  # canonical name -> (pk, name, is_archived)
    service_types: dict  # canonical name -> (pk, name)


@dataclass(frozen=True)
class ImportReport:
    exported_at: datetime | None
    zone: tzinfo
    applied: bool
    totals: dict
    new_categories: tuple
    reused_categories: tuple
    new_types: tuple
    reused_types: tuple
    warnings: tuple
    errors: tuple

    def _when(self, instant):
        local = instant.astimezone(self.zone)
        return f"{local:%d/%m/%Y %H:%M} ({getattr(self.zone, 'key', None) or local.tzname()})"

    def lines(self):
        t = self.totals
        verb = "creados" if self.applied else "se crearían"
        lines = ["ProBikeGarage → Garage" + (f" · volcado del {self._when(self.exported_at)}" if self.exported_at else "")]
        if self.applied:
            lines.append("Importado en una sola transacción.")
        else:
            lines.append("Previsualización: no se ha escrito nada.")
        if t:
            lines += [
                f"Recuentos ({verb}):",
                f"  Categorías: {t['categories_new']} nuevas · {t['categories_reused']} reutilizadas",
                f"  Bicis: {t['bikes']} ({t['bikes_linked']} vinculadas a su bici de Strava · {t['bikes_retired']} retiradas)",
                f"  Material: {t['items']} ({t['items_retired']} retirados)",
                f"  Montajes: {t['installations']} ({t['installations_nested']} dentro de otra pieza · "
                f"{t['installations_since_always']} «desde siempre»)",
                f"  Tipos de intervención: {t['types_new']} nuevos · {t['types_reused']} reutilizados",
                f"  Reglas de mantenimiento: {t['rules']}",
                f"  Vidas útiles: {t['lifespans']}",
                f"  Intervenciones: {t['events']}",
                f"  Lecturas de uso inicial (estimadas): {t['baselines']}",
                f"  Salidas del volcado: {t['rides']} — no se importan: vienen del histórico de Strava (sólo para verificar)",
            ]
        if self.new_categories:
            lines.append("Categorías nuevas: " + ", ".join(self.new_categories))
        if self.reused_categories:
            lines.append("Categorías reutilizadas: " + ", ".join(self.reused_categories))
        if self.new_types:
            lines.append("Tipos de intervención nuevos: " + ", ".join(self.new_types))
        if self.reused_types:
            lines.append("Tipos de intervención reutilizados: " + ", ".join(self.reused_types))
        lines.append(f"Avisos: {len(self.warnings)}")
        lines += [f"  - {warning}" for warning in self.warnings]
        lines.append(f"Errores: {len(self.errors)}")
        lines += [f"  - {error}" for error in self.errors]
        return lines


@dataclass(frozen=True)
class ImportPreview:
    plan: object
    report: ImportReport


@dataclass(frozen=True)
class ImportResult:
    report: ImportReport
    mapping: dict = field(default_factory=dict)


def _owner_state(owner):
    """Four read queries, whatever the size of the Garage or of the dump."""
    categories = {_canonical(name): (pk, name, archived)
                  for pk, name, archived in Category.objects.filter(owner_id=owner.pk).values_list("pk", "name", "is_archived")}
    types = {_canonical(name): (pk, name) for pk, name in ServiceType.objects.filter(owner_id=owner.pk).values_list("pk", "name")}
    return OwnerState(Bike.objects.filter(owner_id=owner.pk).count(), Item.objects.filter(owner_id=owner.pk).count(), categories, types)


def _report(plan, state, *, zone, applied=False):
    errors = [str(error) for error in plan.errors]
    if state.bikes or state.items:
        errors.insert(0, f"Garage: el propietario ya tiene {state.bikes} bicis y {state.items} objetos; la importación sólo se hace "
                         "sobre un Garage sin bicis ni material (un solo uso, sin --force)")
    warnings = [str(warning) for warning in plan.warnings]
    new_categories, reused_categories = [], []
    for name, _ in plan.categories:
        existing = state.categories.get(_canonical(name))
        if existing is None:
            new_categories.append(name)
        else:
            reused_categories.append(existing[1])
            if existing[2]:
                warnings.append(f"Categoría «{existing[1]}»: está archivada y se reutiliza (Garage no admite dos con el mismo nombre)")
    new_types, reused_types = [], []
    for name in plan.service_types:
        existing = state.service_types.get(_canonical(name))
        if existing:
            reused_types.append(existing[1])
        else:
            new_types.append(name)
    totals = {}
    if plan.ok:
        totals = {
            "categories_new": len(new_categories), "categories_reused": len(reused_categories),
            "bikes": len(plan.bikes), "bikes_linked": sum(bool(bike.gear_id) for bike in plan.bikes),
            "bikes_retired": sum(bike.retired_at is not None for bike in plan.bikes),
            "items": len(plan.items), "items_retired": sum(item.retired_at is not None for item in plan.items),
            "installations": len(plan.installations), "installations_nested": sum(m.parent_id is not None for m in plan.installations),
            "installations_since_always": sum(m.since_always for m in plan.installations),
            "types_new": len(new_types), "types_reused": len(reused_types),
            "rules": sum(not rule.life for rule in plan.rules), "lifespans": sum(rule.life for rule in plan.rules),
            "events": len(plan.events), "baselines": len(plan.baselines), "rides": len(plan.rides),
        }
    return ImportReport(plan.exported_at, zone, applied, totals, tuple(new_categories), tuple(reused_categories), tuple(new_types),
                        tuple(reused_types), tuple(warnings), tuple(errors))


def _zone(zone):
    if not isinstance(zone, tzinfo):
        raise TypeError("Use an explicit tzinfo (for example ZoneInfo('UTC')).")
    return zone


def preview(actor, dump, *, zone=UTC):
    """The plan and its report for the actor's Garage: read-only (--dry-run)."""
    owner = require_actor(actor)
    plan = build_plan(dump)
    return ImportPreview(plan, _report(plan, _owner_state(owner), zone=_zone(zone)))


def _row_failure(table, row_id, name, error):
    messages = error.messages if isinstance(error, ValidationError) else [str(error)]
    where = f"{table} {row_id}" + (f" «{name}»" if name else "")
    return ImportFailed({"__all__": [f"{where}: Garage lo rechazó al escribir ({'; '.join(messages)}). No se ha escrito nada."]})


def apply(actor, dump, *, zone):
    """Write the whole plan atomically; ImportRejected (nothing written) when it has errors."""
    zone = _zone(zone)
    plan = build_plan(dump)
    with transaction.atomic():
        owner = _lock_owner(actor)
        state = _owner_state(owner)  # re-read under the lock: nobody adds a bike meanwhile
        report = _report(plan, state, zone=zone)
        if report.errors:
            raise ImportRejected(report)
        mapping = _write(owner, plan, state)
        rebuild_usage(owner)
    report = replace(report, applied=True)
    t = report.totals
    logger.info("probikegarage import: owner=%s categories=%d bikes=%d items=%d installations=%d rules=%d lifespans=%d events=%d baselines=%d",
                owner.pk, t["categories_new"], t["bikes"], t["items"], t["installations"], t["rules"], t["lifespans"], t["events"], t["baselines"])
    return ImportResult(report, mapping)


def _write(owner, plan, state):
    """Caller holds the owner lock inside its transaction and read `state` under it; every write goes through a domain service."""
    names = {**{bike.pbg_id: bike.name for bike in plan.bikes}, **{item.pbg_id: item.name for item in plan.items}}
    mapping = {"format": MAPPING_FORMAT, "version": 1, "exported_at": plan.exported_at.isoformat() if plan.exported_at else None,
               "owner": owner.pk, "bikes": {}, "strava_gear": {}, "components": {}, "installations": {}, "service_intervals": {},
               "services": {}, "baselines": {}}
    categories = {}
    for name, icon in plan.categories:
        key = _canonical(name)
        if key in state.categories:
            categories[key] = state.categories[key][0]
            continue
        try:
            categories[key] = create_inventory(owner, Category, name=name, icon=icon).pk
        except ValidationError as error:
            raise _row_failure("categories", "", name, error) from error
    bikes = {}
    for bike in plan.bikes:
        try:
            obj = create_inventory(owner, Bike, name=bike.name, brand=bike.brand, model=bike.model, notes="")
            bikes[bike.pbg_id] = obj.pk
            if bike.gear_id:
                # An empty name never blanks the one a Strava sync already stored for this gear.
                gear = ensure_gear(owner, bike.gear_id, name=bike.gear_name or None)
                link_gear(owner, gear.pk, obj)
                mapping["strava_gear"][bike.pbg_id] = str(gear.pk)
        except ValidationError as error:
            raise _row_failure("bikes", bike.pbg_id, bike.name, error) from error
        mapping["bikes"][bike.pbg_id] = str(obj.pk)
    items = {}
    for item in plan.items:
        try:
            obj = create_inventory(owner, Item, name=item.name, category=categories[_canonical(item.category)], notes=item.notes)
        except ValidationError as error:
            raise _row_failure("components", item.pbg_id, item.name, error) from error
        items[item.pbg_id] = obj.pk
        mapping["components"][item.pbg_id] = str(obj.pk)
    for mount in plan.installations:
        try:
            obj = create_installation(owner, item=items[mount.component_id], bike=bikes.get(mount.bike_id),
                                      parent_item=items.get(mount.parent_id), started_at=mount.started_at, ended_at=mount.ended_at,
                                      slot=None, notes=mount.notes)
        except ValidationError as error:
            raise _row_failure("installations", mount.pbg_id, names.get(mount.component_id, ""), error) from error
        mapping["installations"][mount.pbg_id] = str(obj.pk)
    types = {}
    for name in plan.service_types:
        key = _canonical(name)
        if key in state.service_types:
            types[key] = state.service_types[key][0]
            continue
        try:
            # «Sustitución» is the useful-life type: created exactly as set_lifespan creates it.
            types[key] = (_life_type(owner, create=True) if key == LIFE_KEY else save_maintenance(owner, ServiceType, name=name)).pk
        except ValidationError as error:
            raise _row_failure("service_types", "", name, error) from error
    for rule in plan.rules:
        try:
            obj = _write_rule(owner, rule, items[rule.component_id], types)
        except ValidationError as error:
            raise _row_failure("service_intervals", ", ".join(rule.interval_ids), names.get(rule.component_id, ""), error) from error
        for interval_id in rule.interval_ids:
            mapping["service_intervals"][interval_id] = str(obj.pk)
    for event in plan.events:
        target = {"item": items[event.component_id]} if event.component_id else {"bike": bikes[event.bike_id]}
        try:
            obj = save_maintenance(owner, ServiceEvent, service_type=types[_canonical(event.service_type)], performed_at=event.performed_at,
                                   notes=event.notes, **target)
        except ValidationError as error:
            raise _row_failure("services", event.service_id, event.service_type, error) from error
        mapping["services"].setdefault(event.service_id, []).append(str(obj.pk))
    for baseline in plan.baselines:
        try:
            obj = record_baseline(owner, item=items[baseline.component_id], metric=baseline.metric, scope="lifetime", cut_at=baseline.cut_at,
                                  value=baseline.value, source=BASELINE_SOURCE, is_estimated=True, notes="")
        except ValidationError as error:
            raise _row_failure("components", baseline.component_id, names.get(baseline.component_id, ""), error) from error
        mapping["baselines"].setdefault(baseline.component_id, []).append(str(obj.pk))
    # After their installations, earliest first: closing an open mount at the first retirement that applies
    # never leaves it ending after a later one.
    retirements = sorted([(item.retired_at, 0, item.pbg_id) for item in plan.items if item.retired_at is not None]
                         + [(bike.retired_at, 1, bike.pbg_id) for bike in plan.bikes if bike.retired_at is not None])
    for when, kind, pbg_id in retirements:
        model, pk = (Item, items[pbg_id]) if kind == 0 else (Bike, bikes[pbg_id])
        try:
            retire_inventory(owner, model, pk, at=when)
        except ValidationError as error:
            raise _row_failure("components" if kind == 0 else "bikes", pbg_id, names.get(pbg_id, ""), error) from error
    return mapping


def _write_rule(owner, rule, item_id, types):
    values = dict(rule.thresholds)
    if not rule.life:
        return save_maintenance(owner, MaintenanceRule, item=item_id, service_type=types[_canonical(rule.service_type)],
                                anchor_at=rule.anchor_at, notes=rule.notes, **values)
    ride_count = values.pop("ride_count", None)
    if values:
        obj = set_lifespan(owner, item_id, start=rule.anchor_at, **{name: values.get(name) for name in LIFE_THRESHOLDS})
    else:  # only a ride count: set_lifespan writes km, hours, days and elevation
        obj = save_maintenance(owner, MaintenanceRule, item=item_id, service_type=_life_type(owner, create=True), anchor_at=rule.anchor_at,
                               ride_count=ride_count)
        ride_count = None
    extra = {}
    if ride_count is not None:
        extra["ride_count"] = ride_count
    if rule.notes:
        extra["notes"] = rule.notes
    return save_maintenance(owner, MaintenanceRule, obj.pk, **extra) if extra else obj


# Verification ---------------------------------------------------------------

DISTANCE, TIME, ELEVATION, COUNT, DAYS = "distance", "time", "elevation", "count", "days"
UNITS = {DISTANCE: "km", TIME: "h", ELEVATION: "m", COUNT: "salidas", DAYS: "días"}


def _within(kind, pbg, garage, *, scale=None):
    """Tolerances of the spec: distance ±0.5 % or ±100 m, time ±60 s, elevation ±1 % (at least 1 m), rides exact, days ±1.

    The percentage applies to `scale` when given (for a rule, the usage ProBikeGarage measured), else to its value.
    """
    difference = abs(garage - pbg)
    reference = abs(scale if scale is not None else pbg)
    if kind == DISTANCE:
        return difference <= max(Decimal(100), reference * Decimal("0.005"))
    if kind == TIME:
        return difference <= 60
    if kind == ELEVATION:
        return difference <= max(Decimal(1), reference * Decimal("0.01"))
    if kind == DAYS:
        return difference <= 1
    return difference == 0


def _display(kind, value):
    if value is None:
        return "—"
    if kind == DISTANCE:
        number = f"{value / 1000:,.1f}"
    elif kind == TIME:
        number = f"{value / 3600:,.1f}"
    elif kind == DAYS:
        number = f"{value:,.1f}"
    else:
        number = f"{value:,.0f}"
    return number.replace(",", " ").replace(".", ",").replace(" ", ".")


@dataclass(frozen=True)
class VerifyRow:
    label: str
    kind: str
    pbg: Decimal | None
    garage: Decimal | None
    ok: bool
    note: str = ""

    @property
    def difference(self):
        return None if self.pbg is None or self.garage is None else self.garage - self.pbg


@dataclass(frozen=True)
class VerifyBlock:
    title: str
    rows: tuple


@dataclass(frozen=True)
class VerifyReport:
    at: datetime
    zone: tzinfo
    blocks: tuple
    rides_total: int
    rides_found: int
    rides_missing: tuple  # ((strava_id, started_at), ...)
    rides_other_bike: int
    notes: tuple

    @property
    def differences(self):
        return sum(not row.ok for block in self.blocks for row in block.rows) + len(self.rides_missing) + self.rides_other_bike

    def lines(self):
        local = self.at.astimezone(self.zone)
        lines = [f"Verificación ProBikeGarage ↔ Garage en el instante del volcado: {local:%d/%m/%Y %H:%M} "
                 f"({getattr(self.zone, 'key', None) or local.tzname()})"]
        for block in self.blocks:
            lines.append("")
            lines.append(block.title)
            if not block.rows:
                lines.append("  (nada que comparar)")
                continue
            width = min(48, max(len(row.label) for row in block.rows))
            lines.append(f"  {'':{width}}  {'Unidad':<8} {'ProBikeGarage':>14} {'Garage':>14} {'Diferencia':>12}")
            for row in block.rows:
                difference = "—" if row.difference is None else _display(row.kind, row.difference)
                mark = "" if row.ok else "  ← diferencia"
                note = f"  ({row.note})" if row.note else ""
                lines.append(f"  {row.label[:width]:{width}}  {UNITS[row.kind]:<8} {_display(row.kind, row.pbg):>14} "
                             f"{_display(row.kind, row.garage):>14} {difference:>12}{mark}{note}")
        lines.append("")
        lines.append(f"Salidas: {self.rides_found} de {self.rides_total} del volcado están en Garage con su fuente de Strava; "
                     f"faltan {len(self.rides_missing)}; {self.rides_other_bike} con otra bici.")
        for strava_id, started_at in self.rides_missing[:50]:
            lines.append(f"  - falta la actividad {strava_id} del {started_at.astimezone(self.zone):%d/%m/%Y %H:%M}")
        if len(self.rides_missing) > 50:
            lines.append(f"  … y {len(self.rides_missing) - 50} más")
        lines += list(self.notes)
        lines.append("")
        lines.append("Sin diferencias." if not self.differences else f"{self.differences} filas con diferencias.")
        return lines


def read_mapping(data):
    """{table: {pbg id: Garage UUID}} from a mapping file's JSON; anything else is ignored."""
    if not isinstance(data, dict) or data.get("format") != MAPPING_FORMAT:
        raise ValueError("El mapa no es un archivo «probikegarage-mapping».")
    result = {}
    for table in ("bikes", "components", "service_intervals"):
        entries = data.get(table) or {}
        result[table] = {}
        if not isinstance(entries, dict):
            continue
        for key, value in entries.items():
            try:
                result[table][key] = UUID(str(value))
            except ValueError:
                continue
    return result


def verify(actor, dump, *, mapping=None, at=None, zone=UTC):
    """Compare the owner's Garage with the dump at `at` (default: the dump's export instant). Read-only."""
    zone = _zone(zone)
    owner = require_actor(actor)
    plan = build_plan(dump)
    if not plan.ok:
        raise ImportRejected(_report(plan, OwnerState(0, 0, {}, {}), zone=zone))
    at = at or plan.exported_at
    mapping = mapping or {}
    bikes = {bike.pk: bike for bike in Bike.objects.filter(owner_id=owner.pk)}
    items = {item.pk: item for item in Item.objects.filter(owner_id=owner.pk).select_related("category")}
    first_mounts = dict(Installation.objects.filter(owner_id=owner.pk).values("item_id").annotate(first=Min("started_at"))
                        .values_list("item_id", "first"))
    # Bikes: by the mapping, else by name (unique).
    bike_of = {}
    for bike in plan.bikes:
        mapped = mapping.get("bikes", {}).get(bike.pbg_id)
        if mapped in bikes:
            bike_of[bike.pbg_id] = mapped
        else:
            same = [pk for pk, obj in bikes.items() if obj.name == bike.name]
            bike_of[bike.pbg_id] = same[0] if len(same) == 1 and not mapping.get("bikes") else None
    # Components: by the mapping, else name + category, then retirement and first mount to tell duplicates apart.
    item_of = {}
    for item in plan.items:
        mapped = mapping.get("components", {}).get(item.pbg_id)
        if mapped in items:
            item_of[item.pbg_id] = mapped
            continue
        if mapping.get("components"):
            item_of[item.pbg_id] = None
            continue
        same = [pk for pk, obj in items.items() if obj.name == item.name and _canonical(obj.category.name) == _canonical(item.category)]
        if len(same) > 1:
            same = [pk for pk in same if items[pk].retired_at == item.retired_at] or same
        if len(same) > 1:
            same = [pk for pk in same if first_mounts.get(pk) == item.first_mount_at] or same
        item_of[item.pbg_id] = same[0] if len(same) == 1 else None
    blocks = [VerifyBlock("Bicis (salidas con esa bici)", tuple(_bike_rows(owner, plan, bikes, bike_of, at))),
              VerifyBlock("Componentes (uso de toda su vida)", tuple(_item_rows(owner, plan, items, item_of, at))),
              VerifyBlock("Reglas (lo que falta para el siguiente servicio)", tuple(_rule_rows(owner, plan, item_of, mapping, at, first_mounts)))]
    found, missing, other_bike = _ride_check(owner, plan, bike_of)
    notes = []
    if plan.rides and not found:
        notes.append(f"0 de {len(plan.rides)} salidas del volcado están en Garage: importa el histórico de Strava "
                     "(Más → Strava → «Importar histórico») y vuelve a verificar.")
    return VerifyReport(at, zone, tuple(blocks), len(plan.rides), found, tuple(missing), other_bike, tuple(notes))


def _bike_rows(owner, plan, bikes, bike_of, at):
    totals = {row["bike_id"]: row for row in Ride.objects.filter(owner_id=owner.pk, bike__isnull=False, started_at__lt=at)
              .values("bike_id").annotate(rides=Count("id"), distance=Sum("distance_m"), moving=Sum("moving_time_s"),
                                          elevation=Sum("elevation_gain_m"))}
    rows = []
    for bike in plan.bikes:
        pk = bike_of[bike.pbg_id]
        if pk is None:
            rows.append(VerifyRow(bike.name, COUNT, bike.usage.rides, None, False, "no está en Garage"))
            continue
        garage = totals.get(pk, {})
        for kind, pbg, value in ((COUNT, bike.usage.rides, Decimal(garage.get("rides") or 0)),
                                 (DISTANCE, bike.usage.distance, garage.get("distance") or Decimal(0)),
                                 (TIME, bike.usage.moving_time, garage.get("moving") or Decimal(0)),
                                 (ELEVATION, bike.usage.elevation_gain, garage.get("elevation") or Decimal(0))):
            rows.append(VerifyRow(bike.name, kind, pbg, value, pbg is None or _within(kind, pbg, value)))
    return rows


def _item_rows(owner, plan, items, item_of, at):
    elevation = dict(ItemUsage.objects.filter(owner_id=owner.pk, started_at__lt=at).values("item_id")
                     .annotate(total=Sum("elevation_gain_m")).values_list("item_id", "total"))
    rows = []
    for item in plan.items:
        label = f"{item.name} · {item.category}"
        pk = item_of[item.pbg_id]
        if pk is None:
            rows.append(VerifyRow(label, DISTANCE, item.usage.distance, None, False, "no está en Garage o es ambiguo"))
            continue
        values = {}
        for metric in ("distance_m", "moving_time_s", "ride_count"):
            reading = summarize_item_usage(owner, pk, metric=metric, scope="lifetime", at=at).reading
            values[metric] = reading.total if reading.total is not None else reading.observed
        for kind, pbg, value in ((DISTANCE, item.usage.distance, values["distance_m"]), (TIME, item.usage.moving_time, values["moving_time_s"]),
                                 (COUNT, item.usage.rides, values["ride_count"]), (ELEVATION, item.usage.elevation_gain, elevation.get(pk) or Decimal(0))):
            note = "uso sin calcular" if value is None else ""
            rows.append(VerifyRow(label, kind, pbg, value, pbg is None or (value is not None and _within(kind, pbg, value)), note))
    return rows


def _rule_rows(owner, plan, item_of, mapping, at, first_mounts):
    due = {result.rule.pk: result for result in maintenance_due(owner, at=at)}
    by_target = {(result.rule.item_id, _canonical(result.rule.service_type.name)): result for result in due.values() if result.rule.item_id}
    names = {item.pbg_id: item.name for item in plan.items}
    kinds = {"distance_m": DISTANCE, "moving_time_s": TIME, "calendar_days": DAYS, "ride_count": COUNT, "elevation_gain_m": ELEVATION}
    rows = []
    for interval in plan.intervals:
        label = f"{names.get(interval.component_id, '')} · {interval.title or LIFE_TYPE}"
        kind = kinds[interval.field]
        pbg = interval.next
        if pbg is not None and kind == DAYS:
            pbg = pbg / Decimal(86400)
        mapped = mapping.get("service_intervals", {}).get(interval.pbg_id)
        result = due.get(mapped) if mapped else None
        if result is None and not mapping.get("service_intervals"):
            item_pk = item_of.get(interval.component_id)
            result = by_target.get((item_pk, LIFE_KEY if not interval.repeat else _canonical(interval.title))) if item_pk else None
        if result is None:
            rows.append(VerifyRow(label, kind, pbg, None, pbg is None, "regla no encontrada"))
            continue
        metric = next((metric for metric in result.metrics if metric.name == interval.field), None)
        value = None if metric is None or metric.value is None else metric.threshold - metric.value
        note = ""
        retired = result.rule.item.retired_at if result.rule.item_id else None
        if (kind == DAYS and metric is not None and retired is not None and retired < at and result.reference_at is not None
                and result.reference_at <= retired):
            # ProBikeGarage stops counting days when a part is retired; Garage's calendar never stops (domain §14).
            value = metric.threshold - _elapsed_days(result.reference_at, retired)
            note = "días hasta su retirada"
        threshold = Decimal(interval.threshold)
        if value is None:
            unused = pbg is not None and (abs(pbg - threshold) <= 1 if kind == DAYS else pbg == threshold)
            if unused and result.reference_at is None and result.rule.item_id not in first_mounts:
                # §2.5: never mounted, «Sin datos» in Garage; ProBikeGarage shows the whole interval left.
                rows.append(VerifyRow(label, kind, pbg, None, True, "sin montar: nada usado, como en ProBikeGarage"))
                continue
            note = "sin referencia o uso desconocido"
        # Distance: ±0.5 % of the usage ProBikeGarage measured since the reference (threshold − next), at least 100 m.
        scale = abs(threshold - pbg) if kind == DISTANCE and pbg is not None else None
        rows.append(VerifyRow(label, kind, pbg, value, pbg is None or (value is not None and _within(kind, pbg, value, scale=scale)), note))
    return rows


def _ride_check(owner, plan, bike_of):
    if not plan.rides:
        return 0, [], 0
    sources = {}
    for external_id, bike_id in ActivitySource.objects.filter(owner_id=owner.pk, source_kind="strava", withdrawn_at__isnull=True,
                                                              external_id__in=[ride.strava_id for ride in plan.rides]) \
            .values_list("external_id", "ride__bike_id"):
        sources[external_id] = bike_id
    found, missing, other_bike = 0, [], 0
    for ride in plan.rides:
        if ride.strava_id not in sources:
            missing.append((ride.strava_id, ride.started_at))
            continue
        found += 1
        if sources[ride.strava_id] != (bike_of.get(ride.bike_id) if ride.bike_id else None):
            other_bike += 1
    return found, missing, other_bike
