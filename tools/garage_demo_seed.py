"""Fictitious Garage demo data (no personal data, no FIT files). Dates are relative to now.

Run only against the disposable demo cluster, through its helper:

    GARAGE_TEST_PYTHON=<python> python3 tools/handoff/garage_demo_pg.py run tools/garage_demo_seed.py

Creates user demo / garage-demo with two bikes, A→B→A saddles, a chain moved
between bikes, shared helmet, shoes per bike profile, ~8 months of rides (with
climbing on all but the oldest, and power on the road rides «with a power
meter», garage-030 phase 3), one ride without a bike (pending review) and
maintenance rules in several states, one of them by climbing.
Refuses to run if the demo user already has inventory.
"""
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "strava_app.settings_test")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.contrib.auth import get_user_model  # noqa: E402
from django.utils import timezone  # noqa: E402

from garage.models import Bike, Category, Item, MaintenanceRule, ServiceEvent, ServiceType  # noqa: E402
from garage.services.installations import create_installation  # noqa: E402
from garage.services.lifespan import set_lifespan  # noqa: E402
from garage.services.maintenance import save_maintenance  # noqa: E402
from garage.services.ownership import create_inventory  # noqa: E402
from garage.services.rides import create_manual_ride  # noqa: E402
from garage.services.usage import rebuild_usage  # noqa: E402
from garage.services.usage_profiles import create_profile_history  # noqa: E402

assert settings.SETTINGS_MODULE == "strava_app.settings_test", "Demo seed only runs with settings_test."
assert settings.DATABASES["default"]["NAME"] == "stravagancia_test_demo", "Demo seed only targets the demo database."

NOW = timezone.now().replace(second=0, microsecond=0)


def ago(days, hour=8):
    return (NOW - timedelta(days=days)).replace(hour=hour, minute=0)


def ride_measures(road_bike, km, moving, old):
    """garage-030 phase 3: climbing on every ride but the oldest (so «N sin desnivel» shows), power only on the
    road rides «with a power meter» (one in three). Whole metres, watts and kJ, as a FIT or Strava would give."""
    measures = {}
    if not old:
        measures["elevation_gain_m"] = km * (12 if road_bike else 18)
    if road_bike and km % 3 == 0:
        average = Decimal(150 + int(km) % 40)
        measures.update(average_power_w=average, max_power_w=(average * Decimal("3.4")).quantize(Decimal(1)),
                        weighted_power_w=(average * Decimal("1.08")).quantize(Decimal(1)),
                        energy_kj=(average * moving / 1000).quantize(Decimal(1)))
    return measures


def main():
    users = get_user_model().objects
    user = users.filter(username="demo").first() or users.create_user("demo", password="garage-demo")
    if Bike.objects.filter(owner=user).exists():
        raise SystemExit("The demo user already has inventory; nothing changed.")

    cat = {name: create_inventory(user, Category, name=name) for name in
           ("Cadenas", "Cubiertas", "Frenos", "Sillines", "Zapatillas", "Cascos", "Luces", "Ruedas", "Casetes", "Discos")}
    road = create_inventory(user, Bike, name="Carretera", brand="Ficticia", model="Endurance")
    gravel = create_inventory(user, Bike, name="Gravel", brand="Ficticia", model="Allroad")

    def item(name, category, **values):
        return create_inventory(user, Item, name=name, category=cat[category], **values)

    chain = item("Cadena 11v", "Cadenas", purchase_amount=Decimal("32.90"), purchase_currency="EUR")
    tire_road = item("Cubierta trasera 28 mm", "Cubiertas")
    tire_gravel = item("Cubierta trasera 40 mm", "Cubiertas")
    pads = item("Pastillas traseras", "Frenos")
    saddle_a = item("Sillín A", "Sillines")
    saddle_b = item("Sillín B", "Sillines")
    shoes_road = item("Zapatillas de carretera", "Zapatillas")
    shoes_gravel = item("Zapatillas de gravel", "Zapatillas")
    helmet = item("Casco", "Cascos")
    item("Luz trasera", "Luces")

    def mount(obj, bike, start, end=None, slot=None):
        create_installation(user, item=obj, bike=bike, parent_item=None, started_at=ago(start, 7),
                            ended_at=ago(end, 7) if end is not None else None, slot=slot)

    mount(chain, gravel, 227, 137, "chain")
    mount(chain, road, 137, None, "chain")
    mount(tire_road, road, 300, None, "rear_tire")
    mount(tire_gravel, gravel, 300, None, "rear_tire")
    mount(pads, gravel, 420, None, "rear_brake")
    mount(saddle_a, road, 300, 200, "saddle")
    mount(saddle_b, road, 200, 100, "saddle")
    mount(saddle_a, road, 100, None, "saddle")
    # Parts inside a part (garage-035): the gravel's rear wheel holds its cassette and brake disc.
    wheel = item("Rueda trasera gravel", "Ruedas")
    cassette = item("Casete 11-42", "Casetes")
    disc = item("Disco 160 mm", "Discos")
    mount(wheel, gravel, 300, None, "rear_wheel")
    create_installation(user, item=cassette, bike=None, parent_item=wheel, started_at=ago(300, 7), ended_at=None, slot=None)
    create_installation(user, item=disc, bike=None, parent_item=wheel, started_at=ago(300, 7), ended_at=None, slot="brake_disc")

    create_profile_history(user, name="Carretera habitual", bike=road, started_at=ago(400, 0), items=[shoes_road, helmet])
    create_profile_history(user, name="Gravel habitual", bike=gravel, started_at=ago(400, 0), items=[shoes_gravel, helmet])

    names = {road: ["Vuelta al embalse", "Puerto corto", "Llano con viento", "Rodaje suave"],
             gravel: ["Pistas del monte", "Camino de la vía", "Sendero del río"]}
    chain_km = Decimal(0)
    for day in range(240, 6, -3):
        bike = road if day % 2 else gravel
        km = Decimal(42 + (day * 7) % 58)
        speed = Decimal(26) if bike is road else Decimal(19)
        start = ago(day, 8 + day % 3)
        moving = (km / speed * 3600).quantize(Decimal(1))
        create_manual_ride(user, started_at=start, bike=bike, name=names[bike][day % len(names[bike])],
                           sport_type="cycling", distance_m=km * 1000, moving_time_s=moving,
                           **ride_measures(bike is road, km, moving, old=day > 200))
        if (bike is gravel and ago(227, 7) <= start < ago(137, 7)) or (bike is road and start >= ago(137, 7)):
            chain_km += km
    # Rider gear has no bike: this ride needs a review (no bike key in its manual fields).
    create_manual_ride(user, started_at=ago(5, 8).replace(minute=12), name="Vuelta por la sierra", sport_type="cycling",
                       distance_m=Decimal("92400"), moving_time_s=Decimal("13260"), elevation_gain_m=Decimal(1850))

    types = {name: save_maintenance(user, ServiceType, name=name) for name in
             ("Cambio de cadena", "Lubricación", "Cambio de pastillas", "Cambio de cubierta", "Revisión del casco",
              "Revisión de rueda", "Cambio de disco")}
    save_maintenance(user, ServiceEvent, item=chain, service_type=types["Cambio de cadena"], performed_at=ago(227, 7),
                     amount=Decimal("32.90"), currency="EUR", notes="Compra y montaje")
    save_maintenance(user, ServiceEvent, item=chain, service_type=types["Lubricación"], performed_at=ago(14, 19))
    save_maintenance(user, ServiceEvent, item=pads, service_type=types["Cambio de pastillas"], performed_at=ago(397, 10),
                     amount=Decimal("24.90"), currency="EUR")
    # Threshold chosen so the observed chain distance sits at ~95 %: «Revisar».
    threshold_km = (chain_km / Decimal("0.95") / 100).quantize(Decimal(1)) * 100
    save_maintenance(user, MaintenanceRule, item=chain, service_type=types["Cambio de cadena"],
                     distance_m=threshold_km * 1000, calendar_days=365)
    save_maintenance(user, MaintenanceRule, item=chain, service_type=types["Lubricación"], distance_m=Decimal(300000))
    save_maintenance(user, MaintenanceRule, item=pads, service_type=types["Cambio de pastillas"], calendar_days=365)
    save_maintenance(user, MaintenanceRule, item=tire_road, service_type=types["Cambio de cubierta"],
                     distance_m=Decimal(5000000), anchor_at=ago(300, 7))
    save_maintenance(user, MaintenanceRule, item=helmet, service_type=types["Revisión del casco"], calendar_days=1825)
    save_maintenance(user, MaintenanceRule, item=wheel, service_type=types["Revisión de rueda"], calendar_days=365, anchor_at=ago(300, 7))
    # The disc rule also counts climbing (what goes up comes down): the first threshold reached wins.
    save_maintenance(user, MaintenanceRule, item=disc, service_type=types["Cambio de disco"], distance_m=Decimal(2500000),
                     elevation_gain_m=Decimal(100000), anchor_at=ago(300, 7))
    set_lifespan(user, cassette, distance_m=Decimal(10000000), start=ago(300, 7))
    result = rebuild_usage(user)
    print(f"Demo listo: usuario demo / garage-demo; cadena {chain_km} km de {threshold_km} km; {len(result.plans)} salidas reconstruidas.")


if __name__ == "__main__":
    main()
