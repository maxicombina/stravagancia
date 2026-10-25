"""garage-032.2: the mobile bike screen and the ride list filtered by bike."""
from decimal import Decimal

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import Bike, Item, MaintenanceRule, ServiceEvent, ServiceType
from .services.installations import create_installation
from .services.maintenance import save_maintenance
from .services.ownership import create_inventory
from .services.rides import create_manual_ride
from .tests_mobile_home import at, garage  # noqa: F401 (fixture)

WRITES = {"INSERT", "UPDATE", "DELETE"}


def page(client, bike):
    with CaptureQueriesContext(connection) as queries:
        response = client.get(reverse("garage:bike-detail", args=[bike.pk]))
    assert response.status_code == 200
    assert not [q for q in queries if q["sql"].lstrip().split()[0].upper() in WRITES]
    return response.content.decode(), len(queries)


class TestBikeScreen:
    def test_page(self, garage, client):
        kind = save_maintenance(garage.owner, ServiceType, name="Lavado")
        save_maintenance(garage.owner, ServiceEvent, bike=garage.road, service_type=kind, performed_at=at(2), amount=Decimal("5"), currency="EUR")
        create_manual_ride(garage.owner, started_at=at(1), bike=garage.road, name="Sin distancia")
        client.force_login(garage.owner)
        html, count = page(client, garage.road)
        assert count <= 34, count  # garage-034: snoozes in the due snapshot; garage-036: the bike's rides for usage between interventions
        assert "<script>" not in html and ' style="' not in html
        for text in ("<h1>Carretera</h1>", "Registrado en Garage", "<b>400</b>", "<b>5</b>", "1 sin distancia: los km son un mínimo.",
                     "Requiere atención", "Cadena 11v", "Revisar", "Km por mes", "Montado ahora", "chain · desde el",
                     "Últimas salidas", "Sin distancia", "Ruta 10", f'href="{reverse("garage:usage-ride-list")}?bike={garage.road.pk}"',
                     "Intervenciones en la bici", "Lavado", "5,00 EUR", f'href="{reverse("garage:service-event-create")}?bike={garage.road.pk}"',
                     "Fotos privadas", "Historial de montajes directos en la bici", 'aria-label="Volver a Garaje"', "<b>16</b>"):
            assert text in html, text
        assert html.count('class="entry compact" href="/garage/rides/') == 5  # last five rides only
        for absent in ("SECRET", "Pista", "Calas"):
            assert absent not in html, absent

    def test_nested_mount_and_its_wear(self, garage, client):
        create_installation(garage.owner, item=garage.shoes, bike=garage.road, parent_item=None, started_at=at(1), ended_at=None, slot=None)
        client.force_login(garage.owner)
        html, _ = page(client, garage.road)
        assert "Sobre Zapatillas" in html and 'class="entry compact nested"' in html
        assert "Calas" in html and "Vencido" in html and "Calas · sobre Zapatillas" in html
        assert "Cambio de cadena · Carretera" not in html and "Cambio de cadena</span>" in html
        other, _ = page(client, garage.gravel)
        assert "Calas" not in other and "Nada montado" in other

    def test_query_count_is_constant(self, garage, client):
        client.force_login(garage.owner)
        page(client, garage.road)
        _, before = page(client, garage.road)
        for number in range(8):
            item = create_inventory(garage.owner, Item, name=f"Pieza {number}", category=garage.helmet.category)
            create_installation(garage.owner, item=item, bike=garage.road, parent_item=None, started_at=at(5), ended_at=None, slot=f"s{number}")
            save_maintenance(garage.owner, MaintenanceRule, item=item, service_type=save_maintenance(garage.owner, ServiceType, name=f"T{number}"),
                             calendar_days=10, anchor_at=at(30))
            create_manual_ride(garage.owner, started_at=at(2 + number), bike=garage.road, name=f"Extra {number}", distance_m=Decimal(1000))
        html, after = page(client, garage.road)
        assert after == before, (before, after)
        assert "Pieza 7" in html

    def test_retired_parts_and_missing_time(self, garage, client):
        from .services.ownership import retire_inventory
        create_manual_ride(garage.owner, started_at=at(1), bike=garage.road, name="Sin tiempo", distance_m=Decimal(1000))
        retire_inventory(garage.owner, Item, garage.chain.pk, at=at(0))
        client.force_login(garage.owner)
        html, _ = page(client, garage.road)
        assert "Cadena 11v" not in html.split("Km por mes")[0] and "1 sin tiempo en movimiento: las horas son un mínimo." in html

    def test_retired_foreign_and_empty(self, garage, client):
        client.force_login(garage.owner)
        html, _ = page(client, garage.retired)
        assert "Retirada el" in html and "Sin salidas con esta bici." in html and "Aún no hay salidas con esta bici" in html
        foreign = Bike.objects.get(name="SECRET bike")
        assert client.get(reverse("garage:bike-detail", args=[foreign.pk])).status_code == 404


class TestRidesByBike:
    def test_filter(self, garage, client):
        client.force_login(garage.owner)
        url = reverse("garage:usage-ride-list")
        html = client.get(url, {"bike": garage.gravel.pk}).content.decode()
        assert "Pista" in html and "Ruta 10" not in html and "Quitar el filtro de Gravel" in html
        assert client.get(url, {"bike": Bike.objects.get(name="SECRET bike").pk}).status_code == 404
        assert client.get(url, {"bike": "not-a-uuid"}).status_code == 404
        assert "Pista" not in client.get(url, {"bike": garage.gravel.pk, "pending": "1"}).content.decode()

    def test_pagination_keeps_the_bike(self, garage, client):
        for number in range(21):
            create_manual_ride(garage.owner, started_at=at(30 + number), bike=garage.gravel, name=f"G{number}", distance_m=Decimal(1000))
        client.force_login(garage.owner)
        html = client.get(reverse("garage:usage-ride-list"), {"bike": garage.gravel.pk}).content.decode()
        assert f"bike={garage.gravel.pk}&amp;page=2" in html and "Página 1 de 2" in html
