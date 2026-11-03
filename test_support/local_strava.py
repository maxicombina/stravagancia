"""Bootstrap of strava_app.settings_local (garage-044): local PostgreSQL plus real Strava.

Install before importing Django, application modules, or dotenv consumers. Unlike
isolation.install(), real HTTP is allowed, but only GET https://www.strava.com/api/v3/...
and POST https://www.strava.com/oauth/token (sockets: only www.strava.com:443); the
database is the local loopback PostgreSQL of isolation.database_config() (the demo
cluster 55433 by default), so Neon is unreachable by construction. The Strava
variables come only from this process's environment (the helper takes them from the
user's shell or from .env, garage-048): this process never reads or writes .env, and
refreshed tokens are never persisted.

Importing this module has no effect on the process: only install_local() does.
"""
import os
import socket
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import requests

from test_support.isolation import database_config

SETTINGS_MODULE = "strava_app.settings_local"
DEMO_DB_PORT = "55433"
DEMO_DB_NAME = "stravagancia_test_demo"
REQUIRED_STRAVA_VARIABLES = ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")
# Only HTTPS to these hosts. Strava announced www.api-v3.strava.com for 2027-06-01: add it here then.
ALLOWED_HTTP_HOSTS = ("www.strava.com",)
HTTPS_PORT = 443
NETWORK_ERROR = "Network access is disabled except local PostgreSQL and www.strava.com"
# The only Strava calls of Garage's token mode (garage-030): reads and the token renewal.
ALLOWED_REQUESTS = {"GET": "/api/v3/", "POST": "/oauth/token"}
# Inherited variables that must never reach the local settings: production database and secrets.
DROPPED_VARIABLES = {"DATABASE_URL", "SECRET_KEY", "STRAVA_ACCESS_TOKEN"}
_installed = False


class NetworkDenied(requests.exceptions.ConnectionError):
    """Raised by every network guard of settings_local.

    An OSError, so urllib3 and http.client turn a refused socket into their own connection
    errors, and a requests.RequestException, so a refused request is too: Garage's Strava
    client reports both as its «network» error instead of a 500.
    """


def reject_pytest():
    if "pytest" in sys.modules or "PYTEST_VERSION" in os.environ:
        raise RuntimeError("strava_app.settings_local never runs under pytest; tests require strava_app.settings_test")


def validate_settings_module(value):
    if value and value != SETTINGS_MODULE:
        raise RuntimeError("DJANGO_SETTINGS_MODULE points to another module; strava_app.settings_local must be the only one")


def missing_strava_variables(environ=None):
    """Names (never values) of the required Strava variables that are absent or empty."""
    environ = os.environ if environ is None else environ
    return [name for name in REQUIRED_STRAVA_VARIABLES if not environ.get(name, "").strip()]


def no_env_file():
    """Where strava_integration.utils looks for .env under these settings: a path that does not exist.

    refresh_access_token() only rewrites its file when os.path.exists() is true, so the
    renewed tokens are never persisted (as on Render). The name stays .env on purpose: if
    the path ever existed, the audit hook would still refuse to open it.
    """
    return Path(tempfile.gettempdir()) / "garage-local-no-env" / ".env"


def http_addresses(hosts=ALLOWED_HTTP_HOSTS):
    return {(host, HTTPS_PORT) for host in hosts}


def check_address(address, allowed=None):
    """Raise unless address[:2] is allowed (default: only the HTTPS hosts by name)."""
    allowed = http_addresses() if allowed is None else allowed
    if not isinstance(address, tuple) or address[:2] not in allowed:
        raise NetworkDenied(NETWORK_ERROR)


def check_request(method, url):
    """Raise unless it is GET https://<allowed host>/api/v3/... or POST https://<allowed host>/oauth/token."""
    if not isinstance(method, str) or not isinstance(url, str):
        raise NetworkDenied(NETWORK_ERROR)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise NetworkDenied(NETWORK_ERROR) from None
    prefix = ALLOWED_REQUESTS.get(method)
    path_ok = prefix is not None and (parts.path.startswith(prefix) if prefix.endswith("/")
                                      else parts.path == prefix and not parts.query)
    if (parts.scheme != "https" or parts.hostname not in ALLOWED_HTTP_HOSTS or port not in (None, HTTPS_PORT)
            or parts.username is not None or parts.password is not None or parts.fragment or not path_ok):
        raise NetworkDenied(NETWORK_ERROR)


def guarded_getaddrinfo(original, allowed, hosts=ALLOWED_HTTP_HOSTS):
    """Wrap getaddrinfo: refuse before resolving, then allow the addresses of an allowed host.

    requests resolves the name and connects to the returned IP; only addresses returned
    for an allowed (host, 443) are added to `allowed` (mutated in place), with that port.
    """
    http = http_addresses(hosts)

    def getaddrinfo(host, port, *args, **kwargs):
        try:
            key = (host, int(port))
        except (TypeError, ValueError):
            raise NetworkDenied(NETWORK_ERROR) from None
        check_address(key, allowed)
        results = original(host, port, *args, **kwargs)
        if key in http:
            for result in results:
                allowed.add((result[4][0], key[1]))
        return results
    return getaddrinfo


def guarded_pg_connect(original, config):
    """Wrap psycopg2.connect: exact host, port, database and role of `config` (libpq bypasses socket)."""
    def pg_connect(dsn=None, *args, **kwargs):
        from psycopg2.extensions import make_dsn, parse_dsn
        if any(key.startswith("PG") for key in os.environ):
            raise RuntimeError("PostgreSQL connection must use the local configuration of settings_local")
        # psycopg2 handles these Python options outside libpq's DSN parser.
        dsn_kwargs = {key: value for key, value in kwargs.items()
                      if key not in {"connection_factory", "cursor_factory", "async", "async_"}}
        params = parse_dsn(make_dsn(dsn, **dsn_kwargs))
        if (params.get("host") != config["HOST"]
                or str(params.get("port")) != config["PORT"]
                or params.get("dbname") != config["NAME"]
                or params.get("user") != config["USER"]
                or set(params) - {"host", "port", "dbname", "user", "password", "connect_timeout", "sslmode", "client_encoding"}):
            raise RuntimeError("PostgreSQL connection must use the local configuration of settings_local")
        return original(dsn, *args, **kwargs)
    return pg_connect


def install_local():
    """Validate everything first (before Django or any connection), then guard the process once."""
    global _installed
    reject_pytest()
    validate_settings_module(os.environ.get("DJANGO_SETTINGS_MODULE"))
    for key in list(os.environ):
        if key in DROPPED_VARIABLES or key.startswith(("DB_", "PG")):
            os.environ.pop(key, None)
    os.environ.setdefault("TEST_DB_PORT", DEMO_DB_PORT)
    os.environ.setdefault("TEST_DB_NAME", DEMO_DB_NAME)
    config = database_config()  # loopback host and stravagancia_test* name, or RuntimeError
    missing = missing_strava_variables()
    if missing:
        from django.core.exceptions import ImproperlyConfigured
        raise ImproperlyConfigured("Run tools/handoff/garage_local_strava.py with the Strava variables exported or in "
                                   ".env (these settings never read it); missing or empty: " + ", ".join(missing))
    if _installed:
        return config
    target = no_env_file()
    if os.path.lexists(target):
        raise RuntimeError("The placeholder token file of settings_local must not exist; remove it: " + str(target))
    os.environ.update({"DJANGO_SETTINGS_MODULE": SETTINGS_MODULE, "PYTHON_DOTENV_DISABLED": "1"})
    os.environ.setdefault("STRAVA_WEBHOOK_VERIFY_TOKEN", "synthetic-local-webhook")  # the webhook is not used locally

    def protect_files(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            if Path(os.fsdecode(args[0])).name == ".env":
                raise RuntimeError("Local Strava settings cannot read or write .env")

    sys.addaudithook(protect_files)
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    dotenv.dotenv_values = lambda *args, **kwargs: {}
    # Reads the exported variables now; never persists the renewed tokens (D4).
    from strava_integration import utils
    utils._ENV_FILE = str(target)

    allowed = http_addresses() | {(config["HOST"], int(config["PORT"]))}
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def connect(sock, address):
        check_address(address, allowed)
        return original_connect(sock, address)

    def connect_ex(sock, address):
        check_address(address, allowed)
        return original_connect_ex(sock, address)

    socket.getaddrinfo = guarded_getaddrinfo(socket.getaddrinfo, allowed)
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    # Before anything is sent, redirects included: only the method and path of each allowed call.
    original_send = requests.sessions.Session.send

    def send(session, request, **kwargs):
        check_request(request.method, request.url)
        return original_send(session, request, **kwargs)

    requests.sessions.Session.send = send
    import psycopg2
    psycopg2.connect = guarded_pg_connect(psycopg2.connect, config)
    _installed = True
    return config
