"""Tests for activity auto-rename (strava_integration/renaming.py)."""

import pytest
from unittest.mock import patch, MagicMock

from strava_integration import renaming
from strava_integration.renaming import (
    is_generic_name,
    shorten_municipality,
    generate_name,
    geocode_point,
    auto_rename_from_strava_data,
    RENAME_MARKER,
)


# ---------------------------------------------------------------------------
# is_generic_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", [
    "Morning Ride",
    "Afternoon Ride",
    "Evening Ride",
    "Night Ride",
    "Lunch Ride",
    "Ride",
    "Workout",
    "Bicicleta de montaña matutina",
    "Bicicleta de montana vespertina",
    "Bicicleta nocturna",
    "Bicicleta matutina",
    "Bicicleta de mediodía",
    "Bicicleta a la hora del almuerzo",
    "Bicicleta por la tarde",
    "Paseo en bici nocturno",
    "Carrera matutina",
    "Tarde en bici",
    "Marcha matutina",
    "Bicicleta de montaña a la hora del almuerzo",
    "Paseo en bici a la hora del almuerzo",
    "Bicicleta de montaña por la tarde",
    "Paseo en bici por la mañana",
    "Entrenamiento por la noche",
])
def test_is_generic_name_matches_known_patterns(name):
    assert is_generic_name(name) is True


@pytest.mark.parametrize("name", [
    "",
    "St Feliu - Castellbisbal ~8km spacing",
    "Vuelta al Garraf",
    "Subida al Tibidabo",
    "Paseo dominical con la familia",
    "Morning Ride to the bakery",  # extra suffix → no longer generic
    "Ride with friends",
])
def test_is_generic_name_rejects_non_generic(name):
    assert is_generic_name(name) is False


# ---------------------------------------------------------------------------
# shorten_municipality
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Sant Feliu de Llobregat", "St Feliu"),
    ("Sant Just Desvern", "St Just Desvern"),
    ("San Sebastián", "St Sebastián"),
    ("el Prat de Llobregat", "Prat"),
    ("la Garriga", "Garriga"),
    ("els Hostalets de Pierola", "Hostalets"),
    ("Barcelona", "Barcelona"),
    ("", ""),
])
def test_shorten_municipality(raw, expected):
    assert shorten_municipality(raw) == expected


# ---------------------------------------------------------------------------
# generate_name (mocking geocode_point)
# ---------------------------------------------------------------------------

def _fake_points(n):
    """Generate n distinct fake (lat, lon) points."""
    return [(40.0 + i * 0.01, -3.0 + i * 0.01) for i in range(n)]


def test_generate_name_basic_format():
    """Output must be 'A - B - C ~8km spacing' with start, end and furthest."""
    points = _fake_points(20)
    names = ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]

    def fake_geocode(lat, lon):
        # Return a deterministic name based on the index.
        idx = int(round((lat - 40.0) / 0.01))
        return (names[idx % len(names)], False)

    with patch.object(renaming, "decode_polyline", return_value=points), \
         patch.object(renaming, "geocode_point", side_effect=fake_geocode):
        name = generate_name("fake-polyline", distance_km=24)

    assert name.endswith(RENAME_MARKER)
    body = name[: -len(RENAME_MARKER)]
    parts = body.split(" - ")
    assert len(parts) >= 2
    # Exactly one bracket marker (the furthest point).
    bracketed = [p for p in parts if p.startswith("[") and p.endswith("]")]
    assert len(bracketed) == 1


def test_generate_name_deduplicates_consecutive():
    """Two consecutive points that geocode to the same name must not appear twice."""
    points = _fake_points(10)

    with patch.object(renaming, "decode_polyline", return_value=points), \
         patch.object(renaming, "geocode_point", return_value=("Same", False)):
        name = generate_name("fake-polyline", distance_km=24)

    body = name[: -len(RENAME_MARKER)]
    parts = body.split(" - ")
    # All points collapse into one (with the bracket on the single survivor).
    assert parts == ["[Same]"]


def test_generate_name_furthest_in_route_order():
    """The bracket must appear at the furthest point's position in route order."""
    # Build points where the furthest-from-start is in the MIDDLE, not at the end.
    points = [
        (40.0, -3.0),     # start
        (40.05, -3.05),
        (40.10, -3.10),   # furthest from start
        (40.05, -3.05),
        (40.0, -3.0),     # end (= start)
    ]
    # Unique names per index.
    by_index = {
        0: "Start",
        1: "Mid1",
        2: "Far",
        3: "Mid2",
        4: "Start",
    }

    def fake_geocode(lat, lon):
        # Map by lat (unique per point in this test).
        for i, (la, lo) in enumerate(points):
            if abs(la - lat) < 1e-6 and abs(lo - lon) < 1e-6:
                return (by_index[i], False)
        return (None, False)

    with patch.object(renaming, "decode_polyline", return_value=points), \
         patch.object(renaming, "geocode_point", side_effect=fake_geocode):
        name = generate_name("fake-polyline", distance_km=16)

    body = name[: -len(RENAME_MARKER)]
    # The bracket must be on "Far" (the furthest), not on any other point.
    assert "[Far]" in body


def test_generate_name_empty_polyline_returns_empty_string():
    with patch.object(renaming, "decode_polyline", return_value=[]):
        assert generate_name("", 10) == ""


def test_generate_name_no_geocode_results_returns_empty_string():
    with patch.object(renaming, "decode_polyline", return_value=_fake_points(5)), \
         patch.object(renaming, "geocode_point", return_value=(None, False)):
        assert generate_name("fake", 10) == ""


# ---------------------------------------------------------------------------
# geocode_point (cache + Overpass-first behaviour)
# ---------------------------------------------------------------------------

def test_geocode_point_cache_hit_avoids_http():
    """A second call with the same lat/lon (same grid) must not hit HTTP."""
    with patch.object(renaming, "overpass_natural", return_value="Pico Tres") as op, \
         patch.object(renaming, "nominatim_reverse") as nom, \
         patch.object(renaming, "time") as fake_time:
        fake_time.sleep = lambda *_: None
        # First call.
        res1 = geocode_point(41.5, 2.1)
        # Second call with near-identical coordinates (same 100m grid).
        res2 = geocode_point(41.5001, 2.1001)

    assert res1 == ("Pico Tres", True)
    assert res2 == res1
    assert op.call_count == 1
    nom.assert_not_called()


def test_geocode_point_overpass_first_then_nominatim():
    """If Overpass returns None, we must fall through to Nominatim."""
    with patch.object(renaming, "overpass_natural", return_value=None) as op, \
         patch.object(renaming, "nominatim_reverse", return_value="Sant Feliu de Llobregat") as nom, \
         patch.object(renaming, "time") as fake_time:
        fake_time.sleep = lambda *_: None
        result = geocode_point(41.38, 2.04)

    assert result == ("St Feliu", False)  # shorten_municipality applied
    op.assert_called_once()
    nom.assert_called_once()


def test_geocode_point_overpass_hit_skips_nominatim():
    with patch.object(renaming, "overpass_natural", return_value="Coll de la Creueta"), \
         patch.object(renaming, "nominatim_reverse") as nom, \
         patch.object(renaming, "time") as fake_time:
        fake_time.sleep = lambda *_: None
        result = geocode_point(42.3, 1.9)

    assert result == ("Coll de la Creueta", True)  # natural feature, no shortening
    nom.assert_not_called()


# ---------------------------------------------------------------------------
# auto_rename_from_strava_data
# ---------------------------------------------------------------------------

def _payload(**overrides):
    base = {
        "id": 12345,
        "name": "Morning Ride",
        "type": "Ride",
        "distance": 30000.0,
        "map": {"summary_polyline": "fake-poly"},
    }
    base.update(overrides)
    return base


def test_auto_rename_happy_path():
    data = _payload()
    with patch.object(renaming, "generate_name", return_value="A - [B] - C ~8km spacing"), \
         patch.object(renaming, "refresh_access_token", return_value="tok"), \
         patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data)

    assert result == "A - [B] - C ~8km spacing"
    put_mock.assert_called_once_with(12345, "A - [B] - C ~8km spacing", "tok")


def test_auto_rename_skips_non_generic_name():
    data = _payload(name="Vuelta al Garraf con amigos")
    with patch.object(renaming, "generate_name") as gen, \
         patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data)

    assert result is None
    gen.assert_not_called()
    put_mock.assert_not_called()


def test_auto_rename_skips_no_polyline():
    data = _payload(map={"summary_polyline": None})
    with patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data)

    assert result is None
    put_mock.assert_not_called()


def test_auto_rename_skips_missing_map():
    data = _payload()
    del data["map"]
    with patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data)

    assert result is None
    put_mock.assert_not_called()


def test_auto_rename_skips_short_distance():
    data = _payload(distance=500.0)  # 0.5 km
    with patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data)

    assert result is None
    put_mock.assert_not_called()


def test_auto_rename_skips_non_ride():
    """Walks/Runs must not be touched (memory: only-rides-in-db)."""
    data = _payload(type="Walk")
    with patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data)

    assert result is None
    put_mock.assert_not_called()


def test_auto_rename_skips_when_generated_name_is_same():
    data = _payload(name="Morning Ride")
    with patch.object(renaming, "generate_name", return_value="Morning Ride"), \
         patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data)

    assert result is None
    put_mock.assert_not_called()


def test_auto_rename_skips_when_generated_name_empty():
    data = _payload()
    with patch.object(renaming, "generate_name", return_value=""), \
         patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data)

    assert result is None
    put_mock.assert_not_called()
