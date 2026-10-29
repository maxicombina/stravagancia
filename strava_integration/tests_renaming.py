"""Tests for activity auto-rename (strava_integration/renaming.py)."""

import json
import logging
import socket

import pytest
import requests
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


@pytest.fixture(autouse=True)
def _no_network_no_sleep(monkeypatch):
    """No test here may reach the network or really sleep.

    Tests that exercise HTTP patch requests.post/get (and socket.getaddrinfo)
    on top of these stand-ins. The geocoding code treats any exception as a
    provider failure, so a forgotten patch shows up as a failed lookup.
    """
    def _blocked(*args, **kwargs):
        raise AssertionError(f"unexpected network access: {args!r}")

    monkeypatch.setattr(renaming.requests, "post", _blocked)
    monkeypatch.setattr(renaming.requests, "get", _blocked)
    monkeypatch.setattr(renaming.requests, "put", _blocked)
    monkeypatch.setattr(renaming.socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(renaming, "GEOCODE_SLEEP_S", 0)


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
    # English multi-word ride variants (MTB/gravel/e-bike)
    "Evening Mountain Bike Ride",
    "Morning Mountain Bike Ride",
    "Afternoon Gravel Ride",
    "Night E-Bike Ride",
    "Lunch E-Mountain Bike Ride",
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
    with patch.object(renaming, "overpass_natural", return_value=("Pico Tres", True)) as op, \
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
    """If Overpass finds no feature, we must fall through to Nominatim."""
    with patch.object(renaming, "overpass_natural", return_value=(None, True)) as op, \
         patch.object(renaming, "nominatim_reverse", return_value="Sant Feliu de Llobregat") as nom, \
         patch.object(renaming, "time") as fake_time:
        fake_time.sleep = lambda *_: None
        result = geocode_point(41.38, 2.04)

    assert result == ("St Feliu", False)  # shorten_municipality applied
    op.assert_called_once()
    nom.assert_called_once()
    # Overpass answered ("no feature here") and Nominatim worked: complete, cached.
    assert renaming._GEO_CACHE[(41.38, 2.04)] == ("St Feliu", False)


def test_geocode_point_overpass_hit_skips_nominatim():
    with patch.object(renaming, "overpass_natural", return_value=("Coll de la Creueta", True)), \
         patch.object(renaming, "nominatim_reverse") as nom, \
         patch.object(renaming, "time") as fake_time:
        fake_time.sleep = lambda *_: None
        result = geocode_point(42.3, 1.9)

    assert result == ("Coll de la Creueta", True)  # natural feature, no shortening
    nom.assert_not_called()


# ---------------------------------------------------------------------------
# HTTP-level helpers (real requests.Response objects, no network)
# ---------------------------------------------------------------------------

PRIMARY, MIRROR = renaming.OVERPASS_ENDPOINTS

HTML_502 = (
    "<html>\r\n<head><title>502 Bad Gateway</title></head>\r\n"
    "<body><center><h1>502 Bad Gateway</h1></center></body></html>"
)


def _http_response(status: int, body: str) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = body.encode("utf-8")
    r.encoding = "utf-8"
    return r


def _overpass_body(*names) -> str:
    return json.dumps({
        "elements": [
            {"type": "node", "id": i, "tags": {"natural": "peak", "name": n}}
            for i, n in enumerate(names)
        ]
    })


def _post_by_url(outcomes: dict):
    """side_effect for requests.post: per URL, a Response, an exception, or a
    list of those consumed one per call."""
    def _post(url, **kwargs):
        outcome = outcomes[url]
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return _post


def _messages(caplog, level):
    return [r.getMessage() for r in caplog.records if r.levelno == level]


def _unreachable():
    return requests.exceptions.ConnectionError("[Errno 101] Network is unreachable")


# ---------------------------------------------------------------------------
# overpass_natural: endpoint fallback
# ---------------------------------------------------------------------------

def test_overpass_primary_connection_error_falls_back_to_mirror(app_caplog):
    post = MagicMock(side_effect=_post_by_url({
        PRIMARY: _unreachable(),
        MIRROR: _http_response(200, _overpass_body("el Tibidabo")),
    }))
    with patch.object(renaming.requests, "post", post):
        result = renaming.overpass_natural(41.4218, 2.1188)

    assert result == ("el Tibidabo", True)
    assert [c.args[0] for c in post.call_args_list] == [PRIMARY, MIRROR]
    for c in post.call_args_list:
        assert c.kwargs["timeout"] == 15
        assert c.kwargs["headers"] == {"User-Agent": renaming.USER_AGENT}
    warnings = _messages(app_caplog, logging.WARNING)
    assert any(PRIMARY in m and "ConnectionError" in m for m in warnings)
    infos = _messages(app_caplog, logging.INFO)
    assert any(MIRROR in m and "el Tibidabo" in m for m in infos)


@pytest.mark.parametrize("primary_outcome, expected_in_warning", [
    (_http_response(502, HTML_502), ["HTTP 502", repr(HTML_502[:200])]),
    (_http_response(200, "\n<html><body>runtime error</body></html>"), ["HTTP 200", "not JSON", "runtime error"]),
    (_http_response(200, '{"remark": "runtime error: Query timed out"}'), ["'elements' list", "Query timed out"]),
    (requests.exceptions.ReadTimeout("read timeout=15"), ["ReadTimeout"]),
], ids=["http-502", "non-json", "json-without-elements", "read-timeout"])
def test_overpass_bad_primary_answer_falls_back_to_mirror(app_caplog, primary_outcome, expected_in_warning):
    post = MagicMock(side_effect=_post_by_url({
        PRIMARY: primary_outcome,
        MIRROR: _http_response(200, _overpass_body("Coll de la Creueta")),
    }))
    with patch.object(renaming.requests, "post", post):
        result = renaming.overpass_natural(42.3, 1.9)

    assert result == ("Coll de la Creueta", True)
    assert [c.args[0] for c in post.call_args_list] == [PRIMARY, MIRROR]
    warnings = [m for m in _messages(app_caplog, logging.WARNING) if PRIMARY in m]
    assert len(warnings) == 1
    for fragment in expected_in_warning:
        assert fragment in warnings[0]


def test_overpass_long_error_body_is_truncated_in_log(app_caplog):
    body = "<html>" + "x" * 5000 + "</html>"
    post = MagicMock(side_effect=_post_by_url({
        PRIMARY: _http_response(504, body),
        MIRROR: _http_response(200, _overpass_body("Puig Major")),
    }))
    with patch.object(renaming.requests, "post", post):
        renaming.overpass_natural(39.8, 2.8)

    (warning,) = [m for m in _messages(app_caplog, logging.WARNING) if PRIMARY in m]
    assert repr(body[:renaming.BODY_SNIPPET_CHARS]) in warning
    assert "x" * (renaming.BODY_SNIPPET_CHARS + 1) not in warning


def test_overpass_all_endpoints_fail_returns_none_not_ok(app_caplog):
    post = MagicMock(side_effect=_post_by_url({
        PRIMARY: _unreachable(),
        MIRROR: _http_response(503, "<html>busy</html>"),
    }))
    with patch.object(renaming.requests, "post", post):
        result = renaming.overpass_natural(41.0, 2.0)

    assert result == (None, False)
    assert post.call_count == 2
    assert any("all 2 endpoints failed" in m for m in _messages(app_caplog, logging.WARNING))


def test_overpass_zero_named_elements_is_a_valid_answer():
    """0 (named) elements = "no peak/saddle here": lookup_ok=True, no fallback."""
    body = json.dumps({"elements": [
        {"type": "node", "tags": {"natural": "peak"}},  # unnamed
        {"type": "node", "tags": None},
    ]})
    post = MagicMock(side_effect=_post_by_url({PRIMARY: _http_response(200, body)}))
    with patch.object(renaming.requests, "post", post):
        result = renaming.overpass_natural(41.38, 2.04)

    assert result == (None, True)
    assert [c.args[0] for c in post.call_args_list] == [PRIMARY]


def test_overpass_starts_from_the_endpoint_that_last_worked(app_caplog):
    post = MagicMock(side_effect=_post_by_url({
        PRIMARY: [_unreachable(), _http_response(200, _overpass_body("Montserrat"))],
        MIRROR: [
            _http_response(200, _overpass_body("el Tibidabo")),
            _http_response(200, json.dumps({"elements": []})),
            _http_response(502, HTML_502),
        ],
    }))
    with patch.object(renaming.requests, "post", post):
        first = renaming.overpass_natural(41.42, 2.12)   # primary down -> mirror
        calls_after_first = len(post.call_args_list)
        second = renaming.overpass_natural(41.50, 2.20)  # mirror FIRST now
        calls_after_second = len(post.call_args_list)
        third = renaming.overpass_natural(41.60, 1.83)   # mirror fails -> primary

    urls = [c.args[0] for c in post.call_args_list]
    assert first == ("el Tibidabo", True)
    assert urls[:calls_after_first] == [PRIMARY, MIRROR]
    assert second == (None, True)
    assert urls[calls_after_first:calls_after_second] == [MIRROR]
    assert third == ("Montserrat", True)
    assert urls[calls_after_second:] == [MIRROR, PRIMARY]
    assert renaming._overpass_preferred_idx == 0
    infos = _messages(app_caplog, logging.INFO)
    assert any(f"preferred endpoint is now {MIRROR}" in m for m in infos)
    assert any(f"preferred endpoint is now {PRIMARY}" in m for m in infos)


# ---------------------------------------------------------------------------
# Connection diagnostic (getaddrinfo on ConnectionError)
# ---------------------------------------------------------------------------

def _fake_addrinfo(host, port, *args, **kwargs):
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("162.55.144.139", port)),
        (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2a01:4f8:261:3c4f::2", port, 0, 0)),
    ]


def test_connection_error_logs_getaddrinfo_once_per_host(app_caplog):
    post = MagicMock(side_effect=_unreachable())
    gai = MagicMock(side_effect=_fake_addrinfo)
    with patch.object(renaming.requests, "post", post), \
         patch.object(renaming.socket, "getaddrinfo", gai):
        assert renaming.overpass_natural(41.0, 2.0) == (None, False)
        assert renaming.overpass_natural(41.1, 2.1) == (None, False)

    assert post.call_count == 4  # both endpoints, both calls
    assert [c.args for c in gai.call_args_list] == [
        ("overpass-api.de", 443), ("overpass.openstreetmap.fr", 443),
    ]
    assert all(c.kwargs == {"type": socket.SOCK_STREAM} for c in gai.call_args_list)
    diag = [m for m in _messages(app_caplog, logging.WARNING) if "Connection diagnostic" in m]
    assert len(diag) == 2
    primary_diag = [m for m in diag if "overpass-api.de" in m]
    assert len(primary_diag) == 1
    assert "[('AF_INET', '162.55.144.139'), ('AF_INET6', '2a01:4f8:261:3c4f::2')]" in primary_diag[0]
    assert "HAS_IPV6=" in primary_diag[0]


def test_connection_diagnostic_survives_getaddrinfo_errors(app_caplog):
    post = MagicMock(side_effect=_post_by_url({
        PRIMARY: _unreachable(),
        MIRROR: _http_response(200, _overpass_body("el Tibidabo")),
    }))
    gai = MagicMock(side_effect=socket.gaierror(-3, "Temporary failure in name resolution"))
    with patch.object(renaming.requests, "post", post), \
         patch.object(renaming.socket, "getaddrinfo", gai):
        assert renaming.overpass_natural(41.42, 2.12) == ("el Tibidabo", True)

    gai.assert_called_once()
    warnings = _messages(app_caplog, logging.WARNING)
    assert any("getaddrinfo failed: gaierror" in m and "overpass-api.de" in m for m in warnings)


def test_connection_diagnostic_never_raises_on_malformed_addrinfo():
    with patch.object(renaming.socket, "getaddrinfo", return_value=[("garbage",)]):
        renaming._log_connection_diagnostic_once(PRIMARY)  # must not raise
    # Reported (attempted) once: a second call doesn't retry the lookup.
    with patch.object(renaming.socket, "getaddrinfo") as gai:
        renaming._log_connection_diagnostic_once(PRIMARY)
    gai.assert_not_called()


def test_non_connection_errors_do_not_trigger_the_diagnostic():
    post = MagicMock(side_effect=requests.exceptions.ReadTimeout("read timeout=15"))
    with patch.object(renaming.requests, "post", post), \
         patch.object(renaming.socket, "getaddrinfo") as gai:
        assert renaming.overpass_natural(41.0, 2.0) == (None, False)
    gai.assert_not_called()


# ---------------------------------------------------------------------------
# nominatim_reverse
# ---------------------------------------------------------------------------

def test_nominatim_ok_returns_municipality():
    body = json.dumps({"address": {"town": "Sant Feliu de Llobregat", "county": "Baix Llobregat"}})
    get = MagicMock(return_value=_http_response(200, body))
    with patch.object(renaming.requests, "get", get):
        assert renaming.nominatim_reverse(41.38, 2.04) == "Sant Feliu de Llobregat"
    assert get.call_args.args[0] == "https://nominatim.openstreetmap.org/reverse"
    assert get.call_args.kwargs["headers"] == {"User-Agent": renaming.USER_AGENT}


@pytest.mark.parametrize("status, body, expected_in_warning", [
    (429, "<html><body><h1>Too Many Requests</h1></body></html>", "HTTP 429"),
    (403, "\n<!DOCTYPE html><html><head><title>Access blocked</title></head></html>", "HTTP 403"),
    (200, "\n<!DOCTYPE html><html><head><title>Error</title></head></html>", "not JSON"),
    (200, '["not", "an", "object"]', "not an object"),
], ids=["http-429", "http-403-html", "200-html", "200-json-list"])
def test_nominatim_bad_response_returns_question_mark(app_caplog, status, body, expected_in_warning):
    get = MagicMock(return_value=_http_response(status, body))
    with patch.object(renaming.requests, "get", get):
        assert renaming.nominatim_reverse(41.38, 2.04) == "?"

    (warning,) = _messages(app_caplog, logging.WARNING)
    assert expected_in_warning in warning
    assert f"HTTP {status}" in warning
    assert repr(body[:renaming.BODY_SNIPPET_CHARS]) in warning


def test_nominatim_exception_returns_question_mark(app_caplog):
    with patch.object(renaming.requests, "get", side_effect=requests.exceptions.ConnectTimeout("boom")):
        assert renaming.nominatim_reverse(41.38, 2.04) == "?"
    assert any("Nominatim exception" in m for m in _messages(app_caplog, logging.WARNING))


# ---------------------------------------------------------------------------
# geocode_point: no negative caching
# ---------------------------------------------------------------------------

def test_geocode_point_failed_lookup_is_not_cached(app_caplog):
    """The 2026-10-25 incident: everything failed once, and the cached
    (None, False) made every later retry a 0.0 s no-op."""
    post = MagicMock(side_effect=_unreachable())
    get = MagicMock(return_value=_http_response(503, "\n<html>Service Unavailable</html>"))
    with patch.object(renaming.requests, "post", post), \
         patch.object(renaming.requests, "get", get), \
         patch.object(renaming.socket, "getaddrinfo", side_effect=_fake_addrinfo):
        first = geocode_point(41.4218, 2.1188)
        second = geocode_point(41.4218, 2.1188)

    assert first == (None, False)
    assert second == (None, False)
    assert post.call_count == 4  # both Overpass endpoints, on both calls
    assert get.call_count == 2   # Nominatim re-queried too
    assert renaming._GEO_CACHE == {}
    infos = _messages(app_caplog, logging.INFO)
    assert not any("Geocode cache hit" in m for m in infos)
    assert sum("not cached" in m for m in infos) == 2


def test_geocode_point_successful_lookup_is_cached():
    post = MagicMock(return_value=_http_response(200, _overpass_body("el Tibidabo")))
    with patch.object(renaming.requests, "post", post):
        first = geocode_point(41.4218, 2.1188)
        second = geocode_point(41.42181, 2.11881)  # same ~100 m cell

    assert first == second == ("el Tibidabo", True)
    assert post.call_count == 1
    assert renaming._GEO_CACHE == {(41.422, 2.119): ("el Tibidabo", True)}


def test_geocode_point_overpass_down_nominatim_ok_returns_municipality_uncached(app_caplog):
    post = MagicMock(side_effect=_unreachable())
    get = MagicMock(return_value=_http_response(
        200, json.dumps({"address": {"town": "Sant Feliu de Llobregat"}}),
    ))
    with patch.object(renaming.requests, "post", post), \
         patch.object(renaming.requests, "get", get), \
         patch.object(renaming.socket, "getaddrinfo", side_effect=_fake_addrinfo):
        first = geocode_point(41.38, 2.04)
        second = geocode_point(41.38, 2.04)

    assert first == second == ("St Feliu", False)
    # Not cached: the second call tries Overpass again (it may find a peak).
    assert post.call_count == 4
    assert get.call_count == 2
    assert renaming._GEO_CACHE == {}
    assert any(
        "not cached: Overpass unavailable" in m
        for m in _messages(app_caplog, logging.INFO)
    )


def test_geocode_point_overpass_failed_mocked_is_not_cached():
    """Same rule at the function level: (None, False) from Overpass + '?' from
    Nominatim is not stored, and the next call asks both providers again."""
    with patch.object(renaming, "overpass_natural", return_value=(None, False)) as op, \
         patch.object(renaming, "nominatim_reverse", return_value="?") as nom:
        assert geocode_point(42.0, 1.5) == (None, False)
        assert geocode_point(42.0, 1.5) == (None, False)

    assert op.call_count == 2
    assert nom.call_count == 2
    assert renaming._GEO_CACHE == {}


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


def test_auto_rename_prefers_full_polyline_over_summary():
    """When both are present, the full `polyline` must be used, not `summary_polyline`."""
    data = _payload(map={"polyline": "full-poly", "summary_polyline": "summary-poly"})
    with patch.object(renaming, "generate_name", return_value="A - [B] - C ~8km spacing") as gen, \
         patch.object(renaming, "refresh_access_token", return_value="tok"), \
         patch.object(renaming, "rename_activity_on_strava"):
        auto_rename_from_strava_data(data)

    gen.assert_called_once()
    # First positional arg is the polyline string
    assert gen.call_args.args[0] == "full-poly"


def test_auto_rename_falls_back_to_summary_polyline():
    """If `polyline` is missing/empty, fall back to `summary_polyline`."""
    data = _payload(map={"polyline": None, "summary_polyline": "summary-poly"})
    with patch.object(renaming, "generate_name", return_value="A - [B] - C ~8km spacing") as gen, \
         patch.object(renaming, "refresh_access_token", return_value="tok"), \
         patch.object(renaming, "rename_activity_on_strava"):
        auto_rename_from_strava_data(data)

    assert gen.call_args.args[0] == "summary-poly"


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


def test_auto_rename_force_bypasses_generic_name_check():
    """With force=True, a non-generic name should still get renamed."""
    data = _payload(name="My custom Garraf loop")
    with patch.object(renaming, "generate_name", return_value="A - [B] - C ~8km spacing"), \
         patch.object(renaming, "refresh_access_token", return_value="tok"), \
         patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data, force=True)

    assert result == "A - [B] - C ~8km spacing"
    put_mock.assert_called_once()


def test_auto_rename_force_still_requires_ride_type():
    """force=True must NOT override the type=Ride check."""
    data = _payload(name="My custom Garraf loop", type="Walk")
    with patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data, force=True)

    assert result is None
    put_mock.assert_not_called()


def test_auto_rename_force_still_requires_polyline():
    """force=True must NOT override the polyline check."""
    data = _payload(name="My custom loop", map={"polyline": None, "summary_polyline": None})
    with patch.object(renaming, "rename_activity_on_strava") as put_mock:
        result = auto_rename_from_strava_data(data, force=True)

    assert result is None
    put_mock.assert_not_called()
