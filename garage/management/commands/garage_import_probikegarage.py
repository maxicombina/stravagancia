"""Import a ProBikeGarage dump (probikegarage-dump v2) into an owner's empty Garage (garage-043)."""
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from garage.importers.probikegarage import DumpError, load_dump
from garage.services.probikegarage_import import ImportRejected, apply, preview


def owner(owner_id):
    actor = get_user_model().objects.filter(pk=owner_id, is_active=True).first()
    if actor is None:
        raise CommandError("Elige un propietario activo existente (--owner).")
    return actor


def zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise CommandError(f"Zona horaria IANA desconocida: {name!r}.") from None


def outside_repository(path):
    """A new file outside the repository: the map names the owner's ProBikeGarage ids."""
    target = Path(path).expanduser().resolve()
    base = Path(settings.BASE_DIR).resolve()
    if target == base or base in target.parents:
        raise CommandError("Guarda el mapa fuera del repositorio (por ejemplo en ~/.cache/stravagancia/probikegarage/).")
    if target.exists():
        raise CommandError(f"{target} ya existe: elige un archivo nuevo para el mapa.")
    if not target.parent.is_dir():
        raise CommandError(f"La carpeta {target.parent} no existe.")
    return target


class Command(BaseCommand):
    help = ("Importa un volcado JSON de ProBikeGarage (probikegarage-dump, versión 2) en el Garage vacío de un propietario: "
            "categorías, bicis vinculadas a su bici de Strava, material, montajes, reglas, vidas útiles, intervenciones y uso "
            "inicial. Las salidas no se importan: vienen del histórico de Strava. Con --dry-run no escribe nada.")

    def add_arguments(self, parser):
        parser.add_argument("dump", help="Ruta del volcado JSON (fuera del repositorio: contiene datos personales)")
        parser.add_argument("--owner", required=True, type=int, help="ID del usuario de Garage, activo y sin bicis ni material")
        parser.add_argument("--dry-run", action="store_true", help="Sólo valida y muestra el informe; no escribe nada")
        parser.add_argument("--mapping", help="Archivo nuevo, fuera del repositorio, para el mapa id de ProBikeGarage → UUID de Garage")
        parser.add_argument("--zone", default="UTC", help="Zona IANA para las fechas del informe (por defecto UTC)")

    def handle(self, *args, **options):
        actor = owner(options["owner"])
        local = zone(options["zone"])
        try:
            dump = load_dump(options["dump"])
        except DumpError as error:
            raise CommandError(str(error)) from None
        target = outside_repository(options["mapping"]) if options["mapping"] and not options["dry_run"] else None
        try:
            if options["dry_run"]:
                report = preview(actor, dump, zone=local).report
                self.stdout.write("\n".join(report.lines()))
                if options["mapping"]:
                    self.stdout.write("(--dry-run: no se guarda el mapa)")
                if report.errors:
                    raise CommandError(f"{len(report.errors)} errores: corrígelos antes de importar. No se ha escrito nada.")
                return
            result = apply(actor, dump, zone=local)
        except ImportRejected as error:
            self.stdout.write("\n".join(error.report.lines()))
            raise CommandError(f"{len(error.report.errors)} errores: no se ha escrito nada.") from None
        except PermissionDenied:
            raise CommandError("Elige un propietario activo existente (--owner).") from None
        except ValidationError as error:
            raise CommandError("; ".join(error.messages)) from None
        self.stdout.write("\n".join(result.report.lines()))
        if target is not None:
            try:
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(result.mapping, handle, ensure_ascii=False, indent=1, sort_keys=True)
                    handle.write("\n")
            except OSError as error:
                # The import is already committed: say so, the verification also works without the map.
                raise CommandError(f"Importado, pero el mapa no se pudo guardar ({error.strerror or error}). "
                                   "garage_probikegarage_verify también compara sin mapa (por nombre y categoría).") from None
            self.stdout.write(f"Mapa guardado en {target}")
