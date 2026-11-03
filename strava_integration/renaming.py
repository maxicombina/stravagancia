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
import socket
import time
from typing import Optional
from urllib.parse import urlsplit

import requests
import urllib3.util.connection

from .utils import refresh_access_token

logger = logging.getLogger(__name__)

# NOTE (Strava API change): the base URL moves to "https://www.api-v3.strava.com"
# effective 2027-06-01. As of 2026-06-02 the new domain is still NXDOMAIN (not
# live yet), so DO NOT switch until a curl to it returns 401 instead of a DNS
# failure. Same constant duplicated in services.py.
STRAVA_API_BASE = "https://www.strava.com/api/v3"
USER_AGENT = "stravagancia-rename/1.0"

SPACING_KM = 8
RENAME_MARKER = " ~8km spacing"

GEOCODE_SLEEP_S = 1.1

# Overpass endpoints, tried in order (starting from the last one that worked).
# The main instance has been flaky: on 2026-10-25 it was unreachable from
# Render for hours ("[Errno 101] Network is unreachable") and answered 502 /
# timed out even from a laptop, while the French mirror answered fine.
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
)
OVERPASS_TIMEOUT_S = 15

# How much of an unexpected response body to put in a WARNING (enough to tell
# an HTML error page or a rate-limit notice apart, short enough for one line).
BODY_SNIPPET_CHARS = 200

# Index in OVERPASS_ENDPOINTS of the endpoint that last answered properly; the
# next lookup starts there, so after one fallback the remaining points of a
# route go straight to the working mirror instead of paying the failure again.
# Per process (like _GEO_CACHE). Rename threads may race on it; the worst case
# is one extra failed attempt, so no lock.
_overpass_preferred_idx = 0

# Hosts for which the getaddrinfo() diagnostic has already been logged in this
# process (logged once per host, on the first ConnectionError).
_CONNECTION_DIAG_REPORTED_HOSTS: set[str] = set()

GENERIC_PATTERNS = [
    r'^(Morning|Afternoon|Evening|Night|Lunch)\s+(Ride|Run|Walk|Hike|Workout)$',
    # English multi-word ride variants Strava emits for MTB/gravel/e-bike, e.g.
    # "Evening Mountain Bike Ride". The single-word pattern above misses these.
    r'^(Morning|Afternoon|Evening|Night|Lunch)\s+(Mountain Bike|Gravel|E-Bike|E-Mountain Bike) Ride$',
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
# Only complete lookups are stored (see geocode_point): a failure is never
# cached, otherwise one provider outage poisons every later retry of the same
# route in this process (what happened on 2026-10-25).
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


def _body_snippet(response) -> str:
    """First BODY_SNIPPET_CHARS of a response body, repr()'d so it stays on one log line."""
    try:
        text = response.text or ""
    except Exception as exc:  # undecodable body, closed stream, ...
        return f"<unreadable body: {exc}>"
    return repr(text[:BODY_SNIPPET_CHARS])


def _log_connection_diagnostic_once(url: str) -> None:
    """
    Log, once per host and process, what getaddrinfo() returns for the host.

    Called after a ConnectionError. urllib3 tries every resolved address in
    order and only reports the last error, so "[Errno 101] Network is
    unreachable" alone doesn't say whether the host resolved to IPv6 only or
    whether IPv4 also failed. The resolved families answer that. Never raises.
    """
    try:
        host = urlsplit(url).hostname
        if not host or host in _CONNECTION_DIAG_REPORTED_HOSTS:
            return
        _CONNECTION_DIAG_REPORTED_HOSTS.add(host)
        # What the outbound HTTP stack is allowed to use (False = A records
        # only; set in settings.py on Render).
        ipv6_enabled = getattr(urllib3.util.connection, "HAS_IPV6", None)
        try:
            infos = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except Exception as exc:
            logger.warning(
                "Connection diagnostic for %s: getaddrinfo failed: %s: %s "
                "(urllib3 HAS_IPV6=%s)",
                host, type(exc).__name__, exc, ipv6_enabled,
            )
            return
        summary = [
            (getattr(family, "name", str(family)), sockaddr[0])
            for family, _type, _proto, _canonname, sockaddr in infos
        ]
        logger.warning(
            "Connection diagnostic for %s: getaddrinfo -> %s (urllib3 HAS_IPV6=%s)",
            host, summary, ipv6_enabled,
        )
    except Exception as exc:
        logger.warning("Connection diagnostic for %s itself failed: %s", url, exc)


def _overpass_attempt(endpoint: str, query: str, lat: float, lon: float) -> Optional[list]:
    """
    POST the query to one Overpass endpoint.

    Returns the response's `elements` list, or None if this endpoint failed:
    request exception, non-200 status, non-JSON body, or JSON without an
    `elements` list. Each failure is logged at WARNING.
    """
    try:
        r = requests.post(
            endpoint,
            data={"data": query},
            headers={"User-Agent": USER_AGENT},
            timeout=OVERPASS_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.warning(
            "Overpass %s failed at (%.5f,%.5f): %s: %s",
            endpoint, lat, lon, type(exc).__name__, exc,
        )
        if isinstance(exc, requests.exceptions.ConnectionError):
            _log_connection_diagnostic_once(endpoint)
        return None
    except Exception as exc:  # defensive: anything else also means "try the next one"
        logger.warning(
            "Overpass %s unexpected error at (%.5f,%.5f): %s: %s",
            endpoint, lat, lon, type(exc).__name__, exc,
        )
        return None

    if r.status_code != 200:
        logger.warning(
            "Overpass %s at (%.5f,%.5f) -> HTTP %s, body=%s",
            endpoint, lat, lon, r.status_code, _body_snippet(r),
        )
        return None
    try:
        payload = r.json()
    except ValueError as exc:
        logger.warning(
            "Overpass %s at (%.5f,%.5f) -> HTTP %s, body is not JSON (%s), body=%s",
            endpoint, lat, lon, r.status_code, exc, _body_snippet(r),
        )
        return None
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list):
        logger.warning(
            "Overpass %s at (%.5f,%.5f) -> HTTP %s, JSON without an 'elements' list, body=%s",
            endpoint, lat, lon, r.status_code, _body_snippet(r),
        )
        return None
    return elements


def overpass_natural(lat: float, lon: float, radius: int = 600) -> tuple[Optional[str], bool]:
    """
    Look up the nearest saddle/peak/mountain_pass within `radius` m.

    Returns (name_or_None, lookup_ok). lookup_ok=True means some endpoint
    answered properly, including "0 elements" (a valid "nothing here");
    lookup_ok=False means every endpoint in OVERPASS_ENDPOINTS failed, so the
    absence of a feature is unknown (and must not be cached).
    """
    global _overpass_preferred_idx

    query = f"""
    [out:json][timeout:10];
    (
      node["natural"="saddle"](around:{radius},{lat},{lon});
      node["natural"="peak"](around:{radius},{lat},{lon});
      node["mountain_pass"="yes"](around:{radius},{lat},{lon});
    );
    out body;
    """
    count = len(OVERPASS_ENDPOINTS)
    start = _overpass_preferred_idx % count
    for offset in range(count):
        idx = (start + offset) % count
        endpoint = OVERPASS_ENDPOINTS[idx]
        elements = _overpass_attempt(endpoint, query, lat, lon)
        if elements is None:
            continue

        if idx != _overpass_preferred_idx:
            logger.info("Overpass: preferred endpoint is now %s", endpoint)
            _overpass_preferred_idx = idx

        named = [
            e for e in elements
            if isinstance(e, dict) and (e.get("tags") or {}).get("name")
        ]
        if named:
            name = named[0]["tags"]["name"]
            logger.info(
                "Overpass (%.5f,%.5f) via %s HTTP 200 -> %r (%d elements)",
                lat, lon, endpoint, name, len(named),
            )
            return name, True
        logger.info(
            "Overpass (%.5f,%.5f) via %s HTTP 200 -> 0 elements",
            lat, lon, endpoint,
        )
        return None, True

    logger.warning(
        "Overpass (%.5f,%.5f): all %d endpoints failed", lat, lon, count,
    )
    return None, False


def nominatim_reverse(lat: float, lon: float) -> str:
    """Return the municipality (town/village/...) or '?' on failure."""
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json"},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        if r.status_code != 200:
            logger.warning(
                "Nominatim (%.5f,%.5f) -> HTTP %s, body=%s",
                lat, lon, r.status_code, _body_snippet(r),
            )
            return "?"
        try:
            payload = r.json()
        except ValueError as exc:
            logger.warning(
                "Nominatim (%.5f,%.5f) -> HTTP %s, body is not JSON (%s), body=%s",
                lat, lon, r.status_code, exc, _body_snippet(r),
            )
            return "?"
        if not isinstance(payload, dict):
            logger.warning(
                "Nominatim (%.5f,%.5f) -> HTTP %s, JSON is not an object, body=%s",
                lat, lon, r.status_code, _body_snippet(r),
            )
            return "?"
        addr = payload.get("address")
        if not isinstance(addr, dict):
            addr = {}
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

    Only complete lookups are cached: a natural feature, or a municipality
    when Overpass did answer (so "no feature here" is known). A municipality
    obtained while Overpass was down is returned but not cached, so a later
    run can still find the peak; (None, False) is never cached.
    """
    key = (round(lat, 3), round(lon, 3))
    if key in _GEO_CACHE:
        cached = _GEO_CACHE[key]
        logger.info("Geocode cache hit (%.5f,%.5f) -> %r", lat, lon, cached)
        return cached

    time.sleep(GEOCODE_SLEEP_S)
    natural, overpass_ok = overpass_natural(lat, lon)
    not_cached_reason: Optional[str] = None
    if natural:
        result: tuple[Optional[str], bool] = (natural, True)
    else:
        time.sleep(GEOCODE_SLEEP_S)
        muni = nominatim_reverse(lat, lon)
        if muni and muni != "?":
            result = (shorten_municipality(muni), False)
            if not overpass_ok:
                not_cached_reason = "Overpass unavailable"
        else:
            result = (None, False)
            not_cached_reason = (
                "no municipality from Nominatim" if overpass_ok
                else "Overpass unavailable and no municipality from Nominatim"
            )

    if not_cached_reason is None:
        _GEO_CACHE[key] = result
        logger.info("Geocode result (%.5f,%.5f) -> %r", lat, lon, result)
    else:
        logger.info(
            "Geocode result (%.5f,%.5f) -> %r (not cached: %s)",
            lat, lon, result, not_cached_reason,
        )
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


def auto_rename_from_strava_data(data: dict, force: bool = False) -> Optional[str]:
    """
    Given a full Strava activity payload, decide whether to rename and perform
    the PUT.

    Returns the new name if renamed, None if skipped. Idempotent: if the name
    is no longer generic, this is a no-op (unless force=True).

    Skip rules (in order):
    - type must be "Ride" (single-user is a cyclist; see memory [[only-rides-in-db]])
    - name must be generic, UNLESS force=True
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

    if force:
        logger.info("auto_rename force=True: bypassing is_generic_name check")
    elif not is_generic_name(name):
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
