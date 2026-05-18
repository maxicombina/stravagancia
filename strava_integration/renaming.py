"""
Auto-rename Strava activities based on the GPS route.

Logic ported from the throwaway scripts used for the historical batch rename
(apply_renames.py, batch_rename.py, catchup_renames.py).

Flow: takes the full Strava payload (from fetch_activity_detail), detects
generic names ("Morning Ride", "Bicicleta de montaña matutina", etc.),
geocodes the polyline (Overpass for peaks/saddles + Nominatim for
municipalities) and PUTs the new name back to Strava.

Format: "St Feliu - [Castellbisbal] - Rubí ~8km spacing", where [brackets]
marks the point furthest from the start.
"""

import logging
import math
import re
import time
from typing import Optional

import requests

from .utils import refresh_access_token

logger = logging.getLogger(__name__)

STRAVA_API_BASE = "https://www.strava.com/api/v3"
USER_AGENT = "stravagancia-rename/1.0"

SPACING_KM = 8
RENAME_MARKER = " ~8km spacing"

GEOCODE_SLEEP_S = 1.1

GENERIC_PATTERNS = [
    r'^(Morning|Afternoon|Evening|Night|Lunch)\s+(Ride|Run|Walk|Hike|Workout)$',
    r'^(Ride|Run|Walk|Hike|Workout)$',
    r'^Bicicleta de monta[ñn]a (matutina|vespertina|nocturna|de mediod[ií]a)$',
    r'^Bicicleta (matutina|vespertina|nocturna|de mediod[ií]a)$',
    r'^Paseo en bici (matutino|vespertino|nocturno|de mediod[ií]a)$',
    r'^Carrera (matutina|vespertina|nocturna|de mediod[ií]a)$',
    r'^(Tarde|Ma[ñn]ana|Noche) en bici$',
    r'^Entrenamiento (matutino|vespertino|nocturno)$',
    r'^Marcha (matutina|vespertina|nocturna)$',
    r'^(Paseo|Caminata) (matutino?|vespertino?|nocturno?)$',
    # Spanish "lunch" variants ("a la hora del almuerzo")
    r'^Bicicleta de monta[ñn]a a la hora del almuerzo$',
    r'^Bicicleta a la hora del almuerzo$',
    r'^Paseo en bici a la hora del almuerzo$',
    r'^Carrera a la hora del almuerzo$',
    r'^Caminata a la hora del almuerzo$',
    r'^Marcha a la hora del almuerzo$',
    r'^Entrenamiento a la hora del almuerzo$',
    r'^Paseo a la hora del almuerzo$',
    # Spanish "por la (tarde|mañana|noche)" variants
    r'^Bicicleta de monta[ñn]a por la (tarde|ma[ñn]ana|noche)$',
    r'^Bicicleta por la (tarde|ma[ñn]ana|noche)$',
    r'^Paseo en bici por la (tarde|ma[ñn]ana|noche)$',
    r'^Carrera por la (tarde|ma[ñn]ana|noche)$',
    r'^Caminata por la (tarde|ma[ñn]ana|noche)$',
    r'^Marcha por la (tarde|ma[ñn]ana|noche)$',
    r'^Entrenamiento por la (tarde|ma[ñn]ana|noche)$',
    r'^Paseo por la (tarde|ma[ñn]ana|noche)$',
]


# Module-level dict, key = (round(lat, 3), round(lon, 3)) ≈ 100m grid precision.
# Tradeoff: the cache only lives while the worker is up. On Render's free tier
# the service sleeps after 15 min idle, so the cache is lost on wake. Real
# volume is ~1 activity every 2-3 days — the cache rarely survives between
# uploads. Acceptable for now; if persistence is needed, move to Django cache
# or a DB table.
_GEO_CACHE: dict[tuple[float, float], tuple[Optional[str], bool]] = {}


def is_generic_name(name: str) -> bool:
    """True if the name matches one of Strava's auto-generated patterns."""
    if not name:
        return False
    return any(re.match(p, name.strip(), re.IGNORECASE) for p in GENERIC_PATTERNS)


def shorten_municipality(name: str) -> str:
    """Shorten a municipality name. Do NOT apply to natural features (peaks/saddles)."""
    if not name:
        return name
    name = re.sub(r'\bSant\b', 'St', name)
    name = re.sub(r'\bSan\b', 'St', name)
    name = re.sub(r'^(el|la|els|les)\s+', '', name, flags=re.IGNORECASE)
    name = re.sub(r"\s+(de la|del|de|d'|des)\s+\w+$", '', name, flags=re.IGNORECASE)
    return name.strip()


def decode_polyline(s: str) -> list[tuple[float, float]]:
    """Decode a Google Encoded Polyline into a list of (lat, lon) tuples."""
    index, lat, lng, pts = 0, 0, 0, []
    while index < len(s):
        for is_lat in (True, False):
            shift, result = 0, 0
            while True:
                b = ord(s[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lat:
                lat += delta
            else:
                lng += delta
        pts.append((lat / 1e5, lng / 1e5))
    return pts


def haversine(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Distance in meters between two (lat, lon) points."""
    R = 6371000
    a1, o1 = math.radians(p1[0]), math.radians(p1[1])
    a2, o2 = math.radians(p2[0]), math.radians(p2[1])
    da, do = a2 - a1, o2 - o1
    a = math.sin(da / 2) ** 2 + math.cos(a1) * math.cos(a2) * math.sin(do / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def overpass_natural(lat: float, lon: float, radius: int = 600) -> Optional[str]:
    """Return the name of the nearest saddle/peak/mountain_pass within radius m, or None."""
    query = f"""
    [out:json][timeout:10];
    (
      node["natural"="saddle"](around:{radius},{lat},{lon});
      node["natural"="peak"](around:{radius},{lat},{lon});
      node["mountain_pass"="yes"](around:{radius},{lat},{lon});
    );
    out body;
    """
    try:
        r = requests.post(
            "https://overpass-api.de/api/interpreter",
            data={"data": query},
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        elements = [e for e in r.json().get("elements", []) if e.get("tags", {}).get("name")]
        if elements:
            name = elements[0]["tags"]["name"]
            logger.info(
                "Overpass (%.5f,%.5f) HTTP %s -> %r (%d elements)",
                lat, lon, r.status_code, name, len(elements),
            )
            return name
        logger.info(
            "Overpass (%.5f,%.5f) HTTP %s -> 0 elements",
            lat, lon, r.status_code,
        )
    except Exception as exc:
        logger.warning("Overpass exception at (%.5f,%.5f): %s", lat, lon, exc)
    return None


def nominatim_reverse(lat: float, lon: float) -> str:
    """Return the municipality (town/village/...) or '?' on failure."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        addr = r.json().get("address", {})
        result = (
            addr.get("town")
            or addr.get("village")
            or addr.get("municipality")
            or addr.get("city")
            or addr.get("county")
            or "?"
        )
        logger.info(
            "Nominatim (%.5f,%.5f) HTTP %s -> %r",
            lat, lon, r.status_code, result,
        )
        return result
    except Exception as exc:
        logger.warning("Nominatim exception at (%.5f,%.5f): %s", lat, lon, exc)
        return "?"


def geocode_point(lat: float, lon: float) -> tuple[Optional[str], bool]:
    """
    Return (name, is_natural). Cached by ~100m grid.
    Priority: Overpass (natural features) → Nominatim (municipality).
    """
    key = (round(lat, 3), round(lon, 3))
    if key in _GEO_CACHE:
        cached = _GEO_CACHE[key]
        logger.info("Geocode cache hit (%.5f,%.5f) -> %r", lat, lon, cached)
        return cached

    time.sleep(GEOCODE_SLEEP_S)
    natural = overpass_natural(lat, lon)
    if natural:
        result: tuple[Optional[str], bool] = (natural, True)
    else:
        time.sleep(GEOCODE_SLEEP_S)
        muni = nominatim_reverse(lat, lon)
        if muni and muni != "?":
            result = (shorten_municipality(muni), False)
        else:
            result = (None, False)

    _GEO_CACHE[key] = result
    logger.info("Geocode result (%.5f,%.5f) -> %r", lat, lon, result)
    return result


def generate_name(polyline_str: str, distance_km: float) -> str:
    """
    Generate a name of the form "A - [B] - C ~8km spacing".
    Sequence: one point every ~8km, start and end always present.
    [Brackets] mark the point furthest from the start (in route order).
    """
    pts = decode_polyline(polyline_str)
    if not pts:
        logger.info("generate_name: polyline decoded to 0 points")
        return ""

    n = max(2, round(distance_km / SPACING_KM))
    step = max(1, len(pts) // n)
    sample_indices = list(range(0, len(pts), step))[:n]

    end_idx = len(pts) - 1
    if end_idx not in sample_indices:
        sample_indices.append(end_idx)

    start = pts[0]
    furthest_idx = max(range(len(pts)), key=lambda i: haversine(start, pts[i]))

    combined: list[tuple[int, bool]] = [(i, False) for i in sample_indices]
    tolerance = max(1, step // 2)
    closest = min(combined, key=lambda x: abs(x[0] - furthest_idx))
    if abs(closest[0] - furthest_idx) <= tolerance:
        combined = [(furthest_idx, True) if c == closest else c for c in combined]
    else:
        combined.append((furthest_idx, True))
    combined.sort(key=lambda x: x[0])

    logger.info(
        "generate_name: %d points, distance_km=%.1f, n=%d, step=%d, "
        "sample_indices=%s, furthest_idx=%d, combined=%s",
        len(pts), distance_km, n, step, sample_indices, furthest_idx, combined,
    )

    items: list[tuple[str, bool]] = []
    for idx, is_furthest in combined:
        name, _is_natural = geocode_point(pts[idx][0], pts[idx][1])
        if name:
            items.append((name, is_furthest))
        else:
            logger.warning(
                "generate_name: idx=%d (furthest=%s) at (%.5f,%.5f) geocoded to None — dropping",
                idx, is_furthest, pts[idx][0], pts[idx][1],
            )

    if not items:
        logger.warning("generate_name: no geocoded items — returning empty name")
        return ""

    # Dedupe consecutive same names — preserve furthest flag if any
    deduped: list[tuple[str, bool]] = [items[0]]
    for name, is_fur in items[1:]:
        if name == deduped[-1][0]:
            deduped[-1] = (name, deduped[-1][1] or is_fur)
        else:
            deduped.append((name, is_fur))

    parts = [f"[{n}]" if f else n for n, f in deduped]
    result = " - ".join(parts) + RENAME_MARKER
    logger.info(
        "generate_name: items=%s deduped=%s -> %r",
        items, deduped, result,
    )
    return result


def rename_activity_on_strava(strava_id: int, new_name: str, token: str) -> dict:
    """PUT /activities/{id} with the new name."""
    r = requests.put(
        f"{STRAVA_API_BASE}/activities/{strava_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": new_name},
        timeout=15,
    )
    logger.info(
        "Strava PUT /activities/%s name=%r -> HTTP %s",
        strava_id, new_name, r.status_code,
    )
    r.raise_for_status()
    return r.json()


def auto_rename_from_strava_data(data: dict) -> Optional[str]:
    """
    Given a full Strava activity payload, decide whether to rename and perform
    the PUT.

    Returns the new name if renamed, None if skipped. Idempotent: if the name
    is no longer generic, this is a no-op.

    Skip rules (in order):
    - type must be "Ride" (single-user is a cyclist; see memory [[only-rides-in-db]])
    - name must be generic
    - data["map"]["summary_polyline"] must exist
    - distance >= 1km (very short routes aren't worth geocoding)
    """
    activity_id = data.get("id")
    name = data.get("name", "")
    activity_type = data.get("type")
    distance = data.get("distance") or 0
    map_data = data.get("map") or {}
    poly_full = map_data.get("polyline")
    poly_summary = map_data.get("summary_polyline")
    logger.info(
        "auto_rename start: id=%s name=%r type=%s distance=%s polyline=%s summary_polyline=%s",
        activity_id, name, activity_type, distance,
        f"{len(poly_full)} chars" if poly_full else None,
        f"{len(poly_summary)} chars" if poly_summary else None,
    )

    if (activity_type or "").strip() != "Ride":
        logger.info("auto_rename skip: type=%r is not 'Ride'", activity_type)
        return None

    if not is_generic_name(name):
        logger.info("auto_rename skip: name not generic: %r", name)
        return None

    # Prefer the full polyline for more representative sampling; fall back to
    # summary_polyline when the full one isn't available (rare — private
    # activities, no-GPS, etc.).
    polyline = poly_full or poly_summary
    if not polyline:
        logger.info("auto_rename skip: no polyline available")
        return None

    distance_km = distance / 1000.0
    if distance_km < 1:
        logger.info("auto_rename skip: distance %.2f km < 1 km", distance_km)
        return None

    new_name = generate_name(polyline, distance_km)
    if not new_name or new_name == name:
        logger.info("auto_rename skip: generated name empty or unchanged (%r)", new_name)
        return None

    token = refresh_access_token()
    rename_activity_on_strava(activity_id, new_name, token)
    # NOTE: we do NOT update Activity.name here. The PUT triggers an `update`
    # webhook that will re-fetch and persist the new name. Source of truth = Strava.
    return new_name
