"""Compare an owner's Garage with a ProBikeGarage dump (garage-043); writes nothing."""
import json

from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from garage.importers.probikegarage import DumpError, load_dump
from garage.services.probikegarage_import import ImportRejected, read_mapping, verify

from .garage_import_probikegarage import owner, zone


class Command(BaseCommand):
    help = ("Compara el Garage de un propietario con un volcado de ProBikeGarage en el instante del volcado: uso de bicis y "
            "componentes, lo que falta en cada regla y qué salidas del volcado tiene Garage desde Strava. No escribe nada.")

    def add_arguments(self, parser):
        parser.add_argument("dump", help="Ruta del volcado JSON")
        parser.add_argument("--owner", required=True, type=int, help="ID del usuario de Garage")
        parser.add_argument("--mapping", help="Mapa guardado por garage_import_probikegarage --mapping (si no, por nombre y categoría)")
        parser.add_argument("--zone", default="UTC", help="Zona IANA para las fechas (por defecto UTC)")

    def handle(self, *args, **options):
        actor = owner(options["owner"])
        local = zone(options["zone"])
        try:
            dump = load_dump(options["dump"])
        except DumpError as error:
            raise CommandError(str(error)) from None
        mapping = None
        if options["mapping"]:
            try:
                with open(options["mapping"], encoding="utf-8") as handle:
                    mapping = read_mapping(json.load(handle))
            except (OSError, ValueError) as error:
                raise CommandError(f"No se puede leer el mapa: {error}") from None
        try:
            report = verify(actor, dump, mapping=mapping, zone=local)
        except ImportRejected as error:
            self.stdout.write("\n".join(error.report.lines()))
            raise CommandError(f"El volcado tiene {len(error.report.errors)} errores.") from None
        except PermissionDenied:
            raise CommandError("Elige un propietario activo existente (--owner).") from None
        self.stdout.write("\n".join(report.lines()))
