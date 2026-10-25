"""Install before importing Django, application modules, or dotenv consumers."""
import os
import re
import socket
import sys
from pathlib import Path

SETTINGS_MODULE = "strava_app.settings_test"
_installed = False


def database_config():
    host = os.environ.get("TEST_DB_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "::1"}:
        raise RuntimeError("TEST_DB_HOST must be a numeric loopback address")
    port = os.environ.get("TEST_DB_PORT", "55432")
    if not port.isascii() or not port.isdecimal() or not 1 <= int(port) <= 65535:
        raise RuntimeError("TEST_DB_PORT must be an integer between 1 and 65535")
    name = os.environ.get("TEST_DB_NAME", "stravagancia_test")
    if not re.fullmatch(r"stravagancia_test(?:_[a-z0-9]+)*", name):
        raise RuntimeError("TEST_DB_NAME must be stravagancia_test with optional lowercase suffixes")
    user = os.environ.get("TEST_DB_USER", "stravagancia_test")
    if not re.fullmatch(r"[a-zA-Z0-9_]+", user):
        raise RuntimeError("TEST_DB_USER must be a plain PostgreSQL role name")
    return {
        "ENGINE": "django.db.backends.postgresql", "HOST": host, "PORT": port,
        "NAME": name, "USER": user,
        "PASSWORD": os.environ.get("TEST_DB_PASSWORD", "stravagancia_test"),
        "CONN_MAX_AGE": 0, "OPTIONS": {"connect_timeout": 3, "sslmode": "disable"},
        "TEST": {"NAME": "test_" + name},
    }


def validate_settings_choice(value):
    if value and value != SETTINGS_MODULE:
        raise RuntimeError("Tests require strava_app.settings_test; alternative settings are rejected")


def install():
    global _installed
    validate_settings_choice(os.environ.get("DJANGO_SETTINGS_MODULE"))
    config = database_config()  # Fail before importing Django or opening connections.
    if _installed:
        return
    # pytest sets PYTEST_VERSION before loading plugins or settings; the demo helper passes
    # GARAGE_STRAVA_USER on purpose, but a pytest run must never inherit Garage keys from the shell.
    under_pytest = bool(os.environ.get("PYTEST_VERSION"))
    for key in list(os.environ):
        if key == "DATABASE_URL" or key.startswith(("DB_", "PG", "STRAVA_")) or (
                under_pytest and key in {"GARAGE_STRAVA_USER", "GARAGE_SYNC_TOKEN"}):
            os.environ.pop(key, None)
    os.environ.update({
        "DJANGO_SETTINGS_MODULE": SETTINGS_MODULE,
        "PYTHON_DOTENV_DISABLED": "1",
        "STRAVA_CLIENT_ID": "synthetic-client", "STRAVA_CLIENT_SECRET": "synthetic-secret",
        "STRAVA_REFRESH_TOKEN": "synthetic-refresh", "STRAVA_ACCESS_TOKEN": "synthetic-access",
        "STRAVA_WEBHOOK_VERIFY_TOKEN": "synthetic-webhook",
    })

    def protect_files(event, args):
        if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
            if Path(os.fsdecode(args[0])).name == ".env":
                raise RuntimeError("Tests cannot read or write .env")

    sys.addaudithook(protect_files)
    import dotenv
    dotenv.load_dotenv = lambda *args, **kwargs: False
    dotenv.dotenv_values = lambda *args, **kwargs: {}

    import requests
    def deny_http(*args, **kwargs):
        raise RuntimeError("Real HTTP is disabled in tests; mock the request")
    requests.sessions.Session.send = deny_http

    allowed = {(config["HOST"], int(config["PORT"]))}
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    def check_address(address):
        if not isinstance(address, tuple) or address[:2] not in allowed:
            raise RuntimeError("Network access is disabled except the configured local test PostgreSQL")
    def connect(sock, address):
        check_address(address)
        return original_connect(sock, address)
    def connect_ex(sock, address):
        check_address(address)
        return original_connect_ex(sock, address)
    original_getaddrinfo = socket.getaddrinfo
    def getaddrinfo(host, port, *args, **kwargs):
        check_address((host, int(port)))
        return original_getaddrinfo(host, port, *args, **kwargs)
    socket.getaddrinfo = getaddrinfo
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    # libpq opens sockets in C; Python socket patches do not protect PostgreSQL.
    import psycopg2
    original_pg_connect = psycopg2.connect
    def pg_connect(dsn=None, *args, **kwargs):
        from psycopg2.extensions import make_dsn, parse_dsn
        if any(key.startswith("PG") for key in os.environ):
            raise RuntimeError("PostgreSQL connection must use the dedicated local test configuration")
        # psycopg2 handles these Python options outside libpq's DSN parser.
        dsn_kwargs = {key: value for key, value in kwargs.items()
                      if key not in {"connection_factory", "cursor_factory", "async", "async_"}}
        params = parse_dsn(make_dsn(dsn, **dsn_kwargs))
        safe_names = {config["NAME"], config["TEST"]["NAME"], "postgres"}
        if (params.get("host") != config["HOST"]
                or str(params.get("port")) != config["PORT"]
                or params.get("dbname") not in safe_names
                or params.get("user") != config["USER"]
                or set(params) - {"host", "port", "dbname", "user", "password", "connect_timeout", "sslmode", "client_encoding"}):
            raise RuntimeError("PostgreSQL connection must use the dedicated local test configuration")
        return original_pg_connect(dsn, *args, **kwargs)
    psycopg2.connect = pg_connect
    _installed = True
