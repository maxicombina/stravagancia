"""Starter set of categories with their icons (garage-041).

Creating it is explicit (a button), idempotent and case-insensitive: only the
names the owner does not have yet are created, under the owner lock. It never
deletes, renames, unarchives or changes the icon of an existing category.
"""
from dataclasses import dataclass

from django.db import IntegrityError, transaction

from garage.icons import ICON_KEYS, match_icon
from garage.models import Category
from .ownership import _lock_owner, _translate_integrity_error, scoped_inventory

# (group, name, icon). The group only orders the screen; it is not stored.
STARTER = (
    ("Transmisión", "Cadena", "chain"),
    ("Transmisión", "Casete", "cassette"),
    ("Transmisión", "Platos", "chainring"),
    ("Transmisión", "Bielas", "crank"),
    ("Transmisión", "Pedalier", "bottom_bracket"),
    ("Transmisión", "Desviador trasero", "derailleur"),
    ("Transmisión", "Desviador delantero", "derailleur"),
    ("Transmisión", "Manetas de cambio", "shifter"),
    ("Transmisión", "Cables y fundas", "cable"),
    ("Ruedas", "Rueda", "wheel"),
    ("Ruedas", "Cubierta", "tire"),
    ("Ruedas", "Cámara", "tube"),
    ("Ruedas", "Buje", "hub"),
    ("Ruedas", "Llanta", "rim"),
    ("Ruedas", "Radios", "spoke"),
    ("Ruedas", "Líquido sellante", "sealant"),
    ("Frenos", "Pastillas", "brake"),
    ("Frenos", "Discos", "disc"),
    ("Frenos", "Pinzas", "caliper"),
    ("Frenos", "Manetas de freno", "brake_lever"),
    ("Dirección y postura", "Horquilla", "fork"),
    ("Dirección y postura", "Dirección", "headset"),
    ("Dirección y postura", "Potencia", "stem"),
    ("Dirección y postura", "Manillar", "handlebar"),
    ("Dirección y postura", "Puños o cinta", "grips"),
    ("Dirección y postura", "Tija", "seatpost"),
    ("Dirección y postura", "Sillín", "saddle"),
    ("Suspensión", "Horquilla de suspensión", "suspension_fork"),
    ("Suspensión", "Amortiguador", "shock"),
    ("Pedales", "Pedales", "pedal"),
    ("Pedales", "Calas", "cleat"),
    ("Equipación", "Casco", "helmet"),
    ("Equipación", "Zapatillas", "shoe"),
    ("Equipación", "Gafas", "glasses"),
    ("Equipación", "Guantes", "gloves"),
    ("Equipación", "Luces", "light"),
    ("Equipación", "Ciclocomputador", "computer"),
    ("Equipación", "Sensores", "sensor"),
    ("Equipación", "Batería", "battery"),
    ("Equipación", "Bidón y portabidón", "bottle"),
    ("Equipación", "Bolsas", "bag"),
    ("Equipación", "Herramientas", "tool"),
)
assert all(icon in ICON_KEYS for _, _, icon in STARTER)


@dataclass(frozen=True)
class StarterResult:
    created: tuple  # the new Category rows, in STARTER order
    existing: tuple  # starter names the owner already had (any case, archived or not)


@dataclass(frozen=True)
class StarterOffer:
    missing: int
    total: int
    next: str  # route name to come back to after creating them


def _canonical(name):
    # Python lower() is at least as broad as PostgreSQL LOWER() in any locale:
    # nothing the unique constraint would reject is ever attempted.
    return name.strip().lower()


def _owned_names(actor):
    return {_canonical(name) for name in scoped_inventory(actor, Category).values_list("name", flat=True)}


def missing_starter(actor):
    """How many starter categories the owner does not have yet (one read query)."""
    names = _owned_names(actor)
    return sum(1 for _, name, _ in STARTER if _canonical(name) not in names)


def starter_offer(actor, next_route):
    """What the «Crear las categorías habituales» button needs, or None when nothing is missing."""
    missing = missing_starter(actor)
    return StarterOffer(missing, len(STARTER), next_route) if missing else None


def suggest_icon(name):
    """The icon key a category name suggests, or '' when none fits."""
    return match_icon(name)


def create_starter_categories(actor):
    """Create the missing starter categories atomically, under the owner lock."""
    try:
        with transaction.atomic():
            owner = _lock_owner(actor)
            # Every category write locks the owner first, so this set is authoritative.
            names = _owned_names(owner)
            created, existing = [], []
            for _, name, icon in STARTER:
                if _canonical(name) in names:
                    existing.append(name)
                    continue
                category = Category(owner=owner, name=name, icon=icon)
                # The owner is the locked user and uniqueness was checked above under the lock (no
                # query per row); the database constraints still apply to the insert.
                category.full_clean(exclude=["owner"], validate_unique=False, validate_constraints=False)
                created.append(category)
                names.add(_canonical(name))
            Category.objects.bulk_create(created)
            return StarterResult(tuple(created), tuple(existing))
    except IntegrityError as error:
        _translate_integrity_error(error)
