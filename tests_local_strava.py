"""garage-044: strava_app.settings_local, its bootstrap and the helper tools/handoff/garage_local_strava.py.

Every child process gets an explicit environment (PATH, HOME, TEST_DB_* of this run,
synthetic Strava values and GARAGE_STRAVA_USER=demo) and nothing else inherited.
No test touches the real .env, Strava or any other host, nor reads ~/.cache/stravagancia.
Since garage-048 the helper reads the Strava variables from .env too: every launch of the
helper sets GARAGE_LOCAL_ENV_FILE to a synthetic or missing file inside tmp_path.
"""
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest

from test_support import local_strava
from test_support.isolation import validate_settings_choice

ROOT = Path(__file__).resolve().parent
HELPER = ROOT / "tools" / "handoff" / "garage_local_strava.py"
SYNTHETIC = {"STRAVA_CLIENT_ID": "synthetic-local-id-4711", "STRAVA_CLIENT_SECRET": "synthetic-local-secret-4712",
             "STRAVA_REFRESH_TOKEN": "synthetic-local-refresh-4713"}
PRODUCTION = {"DATABASE_URL": "postgres://remote:fake-url-4714@production.invalid/production",
              "DB_HOST": "production.invalid", "DB_NAME": "production", "DB_PASSWORD": "fake-db-4715",
              "PGHOSTADDR": "203.0.113.1", "PGSERVICE": "production", "PGOPTIONS": "-c search_path=production",
              "SECRET_KEY": "fake-production-key-4716", "STRAVA_ACCESS_TOKEN": "fake-production-access-4717"}
SECRETS = list(SYNTHETIC.values()) + [PRODUCTION[k] for k in ("DATABASE_URL", "DB_PASSWORD", "SECRET_KEY",
                                                              "STRAVA_ACCESS_TOKEN")]


def child_env(**overrides):
    env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
    env.update({k: v for k, v in os.environ.items() if k.startswith("TEST_DB_")})
    env.update(SYNTHETIC, GARAGE_STRAVA_USER="demo")
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def child(code, *args, **overrides):
    return subprocess.run([sys.executable, "-c", code, *args], cwd=ROOT, env=child_env(**overrides),
                          capture_output=True, text=True, timeout=60)


# 1. Production environment ignored; Strava variables are the exported ones.

def test_settings_local_ignores_production_environment():
    result = child('''
import json, os, sys
from strava_app import settings_local as s
from strava_integration import utils
assert 'strava_app.settings' not in sys.modules
assert 'DATABASE_URL' not in os.environ
assert not any(k.startswith(('DB_', 'PG')) for k in os.environ)
assert 'SECRET_KEY' not in os.environ and 'STRAVA_ACCESS_TOKEN' not in os.environ
assert s.SECRET_KEY == 'synthetic-local-strava-secret-key-never-for-deployment'
assert utils.STRAVA_CLIENT_ID == 'synthetic-local-id-4711'
assert utils.STRAVA_CLIENT_SECRET == 'synthetic-local-secret-4712'
assert utils.STRAVA_REFRESH_TOKEN == 'synthetic-local-refresh-4713'
assert os.environ['DJANGO_SETTINGS_MODULE'] == 'strava_app.settings_local'
assert os.environ['PYTHON_DOTENV_DISABLED'] == '1'
assert s.GARAGE_STRAVA_USER == 'demo' and s.GARAGE_SYNC_TOKEN == '' and s.STRAVA_WEBHOOK_SUBSCRIPTION_ID == ''
assert os.environ['STRAVA_WEBHOOK_VERIFY_TOKEN'] == 'synthetic-local-webhook'
print(json.dumps(s.DATABASES))
''', **PRODUCTION)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)["default"]
    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["HOST"] in {"127.0.0.1", "::1"}
    assert config["PORT"] == os.environ["TEST_DB_PORT"]
    assert config["NAME"] == os.environ["TEST_DB_NAME"]
    assert not any(secret in result.stdout + result.stderr for secret in SECRETS)


def test_settings_local_defaults_to_the_demo_cluster():
    result = child('''
import json
from strava_app import settings_local as s
print(json.dumps(s.DATABASES))
''', TEST_DB_PORT=None, TEST_DB_NAME=None)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)["default"]
    assert (config["HOST"], config["PORT"], config["NAME"]) == ("127.0.0.1", "55433", "stravagancia_test_demo")


@pytest.mark.parametrize("key,value", [("TEST_DB_HOST", "production.invalid"), ("TEST_DB_NAME", "production")])
def test_settings_local_rejects_non_local_database(key, value):
    result = child("import strava_app.settings_local", **{key: value})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr and "TEST_DB_" in result.stderr


def test_settings_local_mirrors_settings_test():
    # The module itself, not django.conf.settings (which prefixes STATIC_URL).
    from strava_app import settings_test as settings
    names = ["INSTALLED_APPS", "MIDDLEWARE", "AUTHENTICATION_BACKENDS", "AXES_FAILURE_LIMIT", "AXES_COOLOFF_TIME",
             "AXES_RESET_ON_SUCCESS", "AXES_LOCKOUT_PARAMETERS", "AXES_IPWARE_PROXY_COUNT",
             "AXES_IPWARE_META_PRECEDENCE_ORDER", "ROOT_URLCONF", "TEMPLATES", "WSGI_APPLICATION",
             "AUTH_PASSWORD_VALIDATORS", "LANGUAGE_CODE", "TIME_ZONE", "USE_I18N", "USE_TZ", "STATIC_URL",
             "DEFAULT_AUTO_FIELD", "GRAFANA_URL"]
    result = child('''
import json, sys
from strava_app import settings_local as s
print(json.dumps({"values": {n: getattr(s, n) for n in sys.argv[1:]}, "debug": s.DEBUG,
                  "hosts": s.ALLOWED_HOSTS, "loggers": s.LOGGING["loggers"],
                  "cookies": [s.SESSION_COOKIE_NAME, s.CSRF_COOKIE_NAME]}))
''', *names)
    assert result.returncode == 0, result.stderr
    local = json.loads(result.stdout)
    assert local["values"] == json.loads(json.dumps({name: getattr(settings, name) for name in names}))
    assert local["debug"] is False
    assert set(local["hosts"]) <= {"localhost", "127.0.0.1", "[::1]"}
    assert {name: logger["level"] for name, logger in local["loggers"].items()} == {
        "garage": "INFO", "strava_integration": "INFO", "django.request": "ERROR"}
    assert not any("whitenoise" in name for name in local["values"]["MIDDLEWARE"])
    # Not the demo's cookies: settings_test serves on the same 127.0.0.1 with another SECRET_KEY (R7).
    assert local["cookies"] == ["garage_local_sessionid", "garage_local_csrftoken"]
    assert not {"SESSION_COOKIE_NAME", "CSRF_COOKIE_NAME"} & set(vars(settings))
    # DEBUG has no switch (R2): the technical 500 page would print the token renewal's locals.
    debug = child("from strava_app import settings_local as s; print(s.DEBUG)", DEBUG="true", GARAGE_LOCAL_DEBUG="1")
    assert debug.returncode == 0, debug.stderr
    assert debug.stdout.strip() == "False"


def test_settings_local_serves_pages_only_to_loopback_hosts():
    result = child('''
import django
django.setup()
from django.test import Client
client = Client()
print(client.get("/accounts/login/", HTTP_HOST="127.0.0.1:8767").status_code,
      client.get("/accounts/login/", HTTP_HOST="192.168.1.10:8767").status_code)
''', DJANGO_SETTINGS_MODULE="strava_app.settings_local")
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["200", "400"]


def test_empty_garage_strava_user_warns_at_startup():
    result = child("from strava_app import settings_local as s; print(repr(s.GARAGE_STRAVA_USER))",
                   GARAGE_STRAVA_USER="")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "''"
    assert "GARAGE_STRAVA_USER is empty" in result.stderr


# 2. Required Strava variables: named when missing, never their values.

@pytest.mark.parametrize("missing", [None, "", "   "])
def test_missing_refresh_token_names_only_the_variable(missing):
    result = child("import strava_app.settings_local", STRAVA_REFRESH_TOKEN=missing, **PRODUCTION)
    assert result.returncode != 0
    assert "ImproperlyConfigured" in result.stderr
    assert "STRAVA_REFRESH_TOKEN" in result.stderr
    assert "STRAVA_CLIENT_SECRET" not in result.stderr and "STRAVA_CLIENT_ID" not in result.stderr
    assert not any(secret in result.stdout + result.stderr for secret in SECRETS)


def test_missing_strava_variables_is_pure():
    assert local_strava.missing_strava_variables({}) == list(local_strava.REQUIRED_STRAVA_VARIABLES)
    assert local_strava.missing_strava_variables(dict(SYNTHETIC)) == []
    assert local_strava.missing_strava_variables(dict(SYNTHETIC, STRAVA_CLIENT_ID=" ")) == ["STRAVA_CLIENT_ID"]


# 3. .env can be neither read nor written; renewed tokens are not persisted.

def test_env_file_untouchable_and_tokens_not_persisted(tmp_path):
    result = child('''
import os, sys
from pathlib import Path
import strava_app.settings_local
import dotenv, requests
from strava_integration import utils
probe = Path(sys.argv[1]) / ".env"
for mode in ("r", "w", "a"):
    try: open(probe, mode)
    except RuntimeError as exc: assert "cannot read or write .env" in str(exc)
    else: raise AssertionError(".env opened")
assert not probe.exists()
assert dotenv.load_dotenv() is False
assert dotenv.dotenv_values() == {}
target = Path(utils._ENV_FILE)
assert target.name == ".env" and target.parent.name == "garage-local-no-env"
assert target != Path(utils.__file__).resolve().parent.parent / ".env"
assert not os.path.exists(utils._ENV_FILE)
parent_existed = target.parent.exists()
calls = []
class Response:
    def raise_for_status(self): pass
    def json(self): return {"access_token": "a", "refresh_token": "r"}
def post(url, data=None, **kwargs):
    calls.append((url, data["client_id"], data["grant_type"]))
    return Response()
requests.post = post
assert utils.refresh_access_token() == "a"
assert calls == [("https://www.strava.com/oauth/token", "synthetic-local-id-4711", "refresh_token")]
assert not target.exists() and target.parent.exists() == parent_existed
print("safe")
''', str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "safe"
    assert list(tmp_path.iterdir()) == []


def test_existing_placeholder_token_file_is_refused(tmp_path):
    # A directory is enough for os.path.lexists(); this process may not open a file named .env,
    # and pytest's later cleanup of tmp_path could not open this directory either: remove it here.
    placeholder = tmp_path / "garage-local-no-env" / ".env"
    placeholder.mkdir(parents=True)
    try:
        result = child("import strava_app.settings_local", TMPDIR=str(tmp_path))
    finally:
        placeholder.rmdir()
    assert result.returncode != 0
    assert "must not exist" in result.stderr


# 4. Network: only local PostgreSQL and www.strava.com:443.

def test_network_guard_in_child_blocks_before_opening_connections():
    result = child('''
import os, socket
resolved, connected = [], []
def resolver(host, port, *args, **kwargs):
    resolved.append((host, port))
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
def backend(sock, address):
    connected.append(address)
    return 0
socket.getaddrinfo = resolver
socket.socket.connect = backend
socket.socket.connect_ex = backend
import strava_app.settings_local
import requests, urllib.error, urllib.request
from test_support.local_strava import NetworkDenied
assert issubclass(NetworkDenied, OSError) and issubclass(NetworkDenied, requests.RequestException)
# Real HTTP is not replaced, only filtered by method and path before anything is sent (R4).
assert requests.sessions.Session.send.__qualname__ == "install_local.<locals>.send"
requests_refused = [("GET", "https://example.com/"), ("GET", "http://www.strava.com/api/v3/athlete"),
                    ("GET", "https://api.probikegarage.com/"), ("GET", "https://nominatim.openstreetmap.org/"),
                    ("GET", "https://www.api-v3.strava.com/api/v3/athlete"),
                    ("PUT", "https://www.strava.com/api/v3/activities/1"),
                    ("DELETE", "https://www.strava.com/api/v3/activities/1"),
                    ("POST", "https://www.strava.com/api/v3/uploads"), ("GET", "https://www.strava.com/oauth/token")]
for method, url in requests_refused:
    try: requests.request(method, url, timeout=1)
    except NetworkDenied as exc: assert "except local PostgreSQL and www.strava.com" in str(exc)
    else: raise AssertionError("request escaped: " + method + " " + url)
# The socket guards raise an OSError: urllib (and urllib3, below) turn it into their connection error (R2).
try: urllib.request.urlopen("https://example.com/", timeout=1)
except urllib.error.URLError as exc: assert isinstance(exc.reason, NetworkDenied)
else: raise AssertionError("urllib escaped")
for call in [lambda: socket.socket().connect(("203.0.113.1", 443)),
             lambda: socket.socket().connect_ex(("127.0.0.1", 80)),
             lambda: socket.socket().connect(("93.184.216.34", 443))]:
    try: call()
    except NetworkDenied as exc: assert "except local PostgreSQL and www.strava.com" in str(exc)
    else: raise AssertionError("socket escaped")
# An allowed request that needs another host (a proxy) ends as requests' own ConnectionError.
os.environ["HTTPS_PROXY"] = "http://proxy.invalid:3128"
try: requests.get("https://www.strava.com/api/v3/athlete", timeout=1)
except NetworkDenied: raise AssertionError("the socket guard should be wrapped by urllib3")
except requests.ConnectionError: pass
else: raise AssertionError("proxy escaped")
del os.environ["HTTPS_PROXY"]
assert resolved == [] and connected == []
assert socket.getaddrinfo("www.strava.com", 443)[0][4] == ("93.184.216.34", 443)
assert resolved == [("www.strava.com", 443)]
db = ("127.0.0.1", int(os.environ["TEST_DB_PORT"]))
for address in [("93.184.216.34", 443), db]:
    assert socket.socket().connect(address) == 0
    assert socket.socket().connect_ex(address) == 0
assert connected == [("93.184.216.34", 443), ("93.184.216.34", 443), db, db]
print("blocked")
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "blocked"


def test_check_address_is_pure_and_allows_only_strava_https():
    local_strava.check_address(("www.strava.com", 443))
    local_strava.check_address(("www.strava.com", 443, 0, 0))
    for address in [("www.strava.com", 80), ("api.probikegarage.com", 443), ("203.0.113.1", 443),
                    ("www.api-v3.strava.com", 443), "www.strava.com", None]:
        with pytest.raises(local_strava.NetworkDenied, match="except local PostgreSQL and www.strava.com"):
            local_strava.check_address(address)


def test_getaddrinfo_wrapper_adds_only_addresses_of_allowed_hosts():
    calls = []

    def resolver(host, port, *args, **kwargs):
        calls.append(host)
        return [(2, 1, 6, "", ("93.184.216.34", 443)), (30, 1, 6, "", ("2001:db8::1", 443, 0, 0))]

    allowed = local_strava.http_addresses()
    before = set(allowed)
    getaddrinfo = local_strava.guarded_getaddrinfo(resolver, allowed)
    with pytest.raises(local_strava.NetworkDenied):
        local_strava.check_address(("93.184.216.34", 443), allowed)
    for host, port in [("api.probikegarage.com", 443), ("www.strava.com", 80), ("www.strava.com", None),
                       ("www.strava.com", "https")]:
        with pytest.raises(local_strava.NetworkDenied):
            getaddrinfo(host, port)
    assert calls == [] and allowed == before
    assert getaddrinfo("www.strava.com", "443") == resolver("www.strava.com", 443)
    assert allowed == before | {("93.184.216.34", 443), ("2001:db8::1", 443)}
    local_strava.check_address(("93.184.216.34", 443), allowed)
    local_strava.check_address(("2001:db8::1", 443, 0, 0), allowed)
    for address in [("93.184.216.34", 80), ("93.184.216.35", 443)]:
        with pytest.raises(local_strava.NetworkDenied):
            local_strava.check_address(address, allowed)


def test_check_request_allows_only_api_reads_and_the_token_renewal():
    for method, url in [("GET", "https://www.strava.com/api/v3/athlete"),
                        ("GET", "https://www.strava.com/api/v3/athlete/activities?after=0&page=1&per_page=50"),
                        ("GET", "https://www.strava.com:443/api/v3/activities/1"),
                        ("POST", "https://www.strava.com/oauth/token")]:
        local_strava.check_request(method, url)
    for method, url in [("PUT", "https://www.strava.com/api/v3/activities/1"),
                        ("DELETE", "https://www.strava.com/api/v3/activities/1"),
                        ("POST", "https://www.strava.com/api/v3/uploads"),
                        ("GET", "https://www.strava.com/oauth/token"),
                        ("POST", "https://www.strava.com/oauth/token?refresh_token=x"),
                        ("POST", "https://www.strava.com/oauth/deauthorize"),
                        ("GET", "http://www.strava.com/api/v3/athlete"),
                        ("GET", "https://www.strava.com:8443/api/v3/athlete"),
                        ("GET", "https://user:pass@www.strava.com/api/v3/athlete"),
                        ("GET", "https://www.strava.com/api/v3/athlete#x"),
                        ("GET", "https://www.strava.com/api/v2/athlete"),
                        ("GET", "https://www.strava.com/"),
                        ("GET", "https://api.probikegarage.com/api/v3/athlete"),
                        ("GET", "https://www.api-v3.strava.com/api/v3/athlete"),
                        ("HEAD", "https://www.strava.com/api/v3/athlete"),
                        ("get", "https://www.strava.com/api/v3/athlete"),
                        ("GET", "https://www.strava.com:x/api/v3/athlete"), ("GET", None)]:
        with pytest.raises(local_strava.NetworkDenied, match="except local PostgreSQL and www.strava.com"):
            local_strava.check_request(method, url)


def test_a_guard_trip_is_a_network_error_for_garage_not_a_500():
    """R2: refused by a guard (here the socket of a proxy), Garage's client reports «network»."""
    result = child('''
import socket
resolved = []
def resolver(host, port, *args, **kwargs):
    resolved.append(host)
    raise AssertionError("resolver reached")
socket.getaddrinfo = resolver
import strava_app.settings_local
import django
django.setup()
from garage.services.strava_client import StravaClient, StravaError
try:
    StravaClient().athlete()
except StravaError as error:
    print(error.code, resolved)
''', HTTPS_PROXY="http://proxy.invalid:3128")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "network []"
    assert not any(secret in result.stdout + result.stderr for secret in SECRETS)


def test_pg_connect_wrapper_requires_the_exact_local_database(monkeypatch):
    for key in [k for k in os.environ if k.startswith("PG")]:
        monkeypatch.delenv(key)
    config = {"HOST": "127.0.0.1", "PORT": "55433", "NAME": "stravagancia_test_demo", "USER": "stravagancia_test"}
    connect = local_strava.guarded_pg_connect(lambda *args, **kwargs: "connected", config)
    params = {"host": "127.0.0.1", "port": "55433", "dbname": "stravagancia_test_demo", "user": "stravagancia_test"}
    assert connect(**params, password="x", connect_timeout=3, sslmode="disable") == "connected"
    for change in [{"host": "production.invalid"}, {"port": "5432"}, {"dbname": "postgres"},
                   {"dbname": "test_stravagancia_test_demo"}, {"user": "neondb_owner"}, {"service": "production"},
                   {"options": "-c search_path=production"}]:
        with pytest.raises(RuntimeError, match="local configuration of settings_local"):
            connect(**dict(params, **change))
    with pytest.raises(RuntimeError):
        connect("postgresql://user:fake@production.invalid/production")
    monkeypatch.setenv("PGHOSTADDR", "203.0.113.1")
    with pytest.raises(RuntimeError):
        connect(**params)


def test_django_connection_parameters_pass_the_pg_guard():
    result = child('''
import psycopg2
calls = []
def backend(*args, **kwargs):
    calls.append(kwargs.get("dbname"))
    return "connected"
psycopg2.connect = backend
import strava_app.settings_local as s
from django.db.backends.postgresql.base import DatabaseWrapper
params = DatabaseWrapper(s.DATABASES["default"]).get_connection_params()
assert "cursor_factory" in params
assert psycopg2.connect(**params) == "connected"
for change in [{"HOST": "production.invalid"}, {"NAME": "postgres"}, {"PORT": "5432"}]:
    remote = DatabaseWrapper(dict(s.DATABASES["default"], **change), alias="remote").get_connection_params()
    try: psycopg2.connect(**remote)
    except RuntimeError: pass
    else: raise AssertionError("unsafe connection accepted")
assert calls == [s.DATABASES["default"]["NAME"]]
print("safe")
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "safe"


def test_importing_the_bootstrap_has_no_effect_on_this_process():
    import socket
    import requests
    assert local_strava._installed is False
    assert socket.getaddrinfo.__module__ != local_strava.__name__
    assert "deny_http" in requests.sessions.Session.send.__name__  # still the suite's guard


# 5. manage.py with the local settings, and their refusals.

def test_manage_check_with_local_settings():
    result = subprocess.run([sys.executable, "manage.py", "check", "--settings=strava_app.settings_local"], cwd=ROOT,
                            env=child_env(**PRODUCTION), capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "System check identified no issues" in result.stdout
    assert not any(secret in result.stdout + result.stderr for secret in SECRETS)


def test_manage_check_refused_under_pytest():
    result = subprocess.run([sys.executable, "manage.py", "check", "--settings=strava_app.settings_local"], cwd=ROOT,
                            env=child_env(PYTEST_VERSION="1"), capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    assert "pytest" in result.stderr and "RuntimeError" in result.stderr


@pytest.mark.parametrize("code,env", [
    ("import sys, types; sys.modules['pytest'] = types.ModuleType('pytest'); import strava_app.settings_local", {}),
    ("import strava_app.settings_local", {"DJANGO_SETTINGS_MODULE": "strava_app.settings"}),
    ("import strava_app.settings_local", {"DJANGO_SETTINGS_MODULE": "strava_app.settings_test"}),
    ("from test_support.local_strava import install_local; install_local()", {"PYTEST_VERSION": "1"}),
])
def test_settings_local_refusals(code, env):
    result = child(code, **env)
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "pytest" in result.stderr or "DJANGO_SETTINGS_MODULE" in result.stderr


# 6. Helper tools/handoff/garage_local_strava.py.

def require_synthetic_env_file(env, tmp_path):
    """Refuse to launch the helper unless GARAGE_LOCAL_ENV_FILE points inside tmp_path.

    Without it the helper reads the repository's real .env (garage-048) and would hand real
    credentials to the fake Python: never in a test (D4'.7).
    """
    value = env.get("GARAGE_LOCAL_ENV_FILE")
    if not value or not Path(value).resolve().is_relative_to(tmp_path.resolve()):
        raise AssertionError("the helper would read the real .env: set GARAGE_LOCAL_ENV_FILE inside tmp_path")


LAUNCH_EVENTS = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn"}
_launch_guard_installed = False


def helper_launch_refusal(args):
    """Why a process launch (the audit arguments of a LAUNCH_EVENTS event) could read the real .env, or None.

    Only a launch that names the helper matters. The environment it gets (its env argument, else
    this process's) must set GARAGE_LOCAL_ENV_FILE to an absolute path that, with symlinks and «..»
    resolved, lies inside the temporary directory (where tmp_path is): otherwise the helper reads
    <repo>/.env (garage-048).
    """
    words, env = [], None
    for arg in args:
        if isinstance(arg, Mapping):
            env = arg
            continue
        for item in arg if isinstance(arg, (list, tuple)) else [arg]:
            if isinstance(item, (str, bytes, os.PathLike)):
                words.append(os.fsdecode(item))
    if not any(HELPER.name in word for word in words):
        return None
    value = (os.environ if env is None else env).get("GARAGE_LOCAL_ENV_FILE")
    path = Path(os.fsdecode(value)) if isinstance(value, (str, bytes)) and value else None
    if (path is None or not path.is_absolute()
            or not path.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())):
        return "the helper would read the real .env: set GARAGE_LOCAL_ENV_FILE to an absolute path inside tmp_path"
    return None


def install_helper_launch_guard():
    """D4'.7 at run time: refuse, in this pytest process, every launch of the helper that could read the real .env.

    An audit hook sees every subprocess, os.system, os.exec* and os.posix_spawn, also those that
    bypass the fixtures. Installed once per process; every test module that runs the helper calls it.
    """
    global _launch_guard_installed
    if _launch_guard_installed:
        return

    def guard(event, args):
        if event in LAUNCH_EVENTS:
            refusal = helper_launch_refusal(args)
            if refusal:
                raise RuntimeError(refusal)

    sys.addaudithook(guard)
    _launch_guard_installed = True


install_helper_launch_guard()


@pytest.fixture
def helper(tmp_path):
    """Run the helper with a fake GARAGE_TEST_PYTHON that dumps its environment (keys, Strava digests) and argv.

    GARAGE_LOCAL_ENV_FILE always points inside tmp_path, by default to a file that does not exist.
    """
    fake = tmp_path / "fake-python"
    fake.write_text("#!" + sys.executable + "\n" + '''import hashlib, json, os, sys
strava = ("STRAVA_CLIENT_ID", "STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN")
print("FAKE " + json.dumps({"keys": sorted(os.environ), "argv": sys.argv[1:], "cwd": os.getcwd(),
                            "dsm": os.environ.get("DJANGO_SETTINGS_MODULE"),
                            "db": [os.environ.get("TEST_DB_HOST"), os.environ.get("TEST_DB_PORT"),
                                   os.environ.get("TEST_DB_NAME")],
                            "strava": {k: hashlib.sha256(os.environ[k].encode()).hexdigest() if k in os.environ
                                       else None for k in strava}}))
''')
    fake.chmod(0o700)
    state = tmp_path / "demo-state.json"
    state.write_text(json.dumps({"root": "/private/tmp/garage018-demo-synthetic", "port": 55433}))
    env_file = tmp_path / "missing-strava.env"
    inherited = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path), "LANG": "C",
                 "GARAGE_TEST_PYTHON": str(fake), "GARAGE_DEMO_STATE": str(state),
                 "GARAGE_LOCAL_ENV_FILE": str(env_file)}
    unsafe = dict(PRODUCTION, DJANGO_SETTINGS_MODULE="strava_app.settings", PYTEST_ADDOPTS="-p no:cacheprovider",
                  PYTHONPATH=str(tmp_path), GARAGE_S3_BUCKET="synthetic-bucket", AWS_SECRET_ACCESS_KEY="fake-aws-4718",
                  TEST_DB_PORT="1", TEST_DB_NAME="stravagancia_test_other", STRAVA_WEBHOOK_VERIFY_TOKEN="fake-4719",
                  GARAGE_LOCAL_DEBUG="1", DEBUG="true")

    def run(*args, **overrides):
        env = dict(inherited, **unsafe, **SYNTHETIC, GARAGE_STRAVA_USER="demo")
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        require_synthetic_env_file(env, tmp_path)
        result = subprocess.run([sys.executable, str(HELPER), *args], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=60)
        fake_lines = [line[5:] for line in result.stdout.splitlines() if line.startswith("FAKE ")]
        result.fake = json.loads(fake_lines[0]) if fake_lines else None
        return result
    run.env_file = env_file
    return run


BASE_KEYS = {"PATH", "HOME", "LANG", "LC_ALL", "DJANGO_SETTINGS_MODULE", "TEST_DB_HOST", "TEST_DB_PORT",
             "TEST_DB_NAME", "TEST_DB_USER", "TEST_DB_PASSWORD"}


def visible_keys(fake):
    # macOS may add its CoreFoundation encoding variable to any process; it carries no secret.
    return {key for key in fake["keys"] if key != "__CF_USER_TEXT_ENCODING"}


def test_helper_check_without_secret_lists_names_only(helper):
    result = helper("check", STRAVA_CLIENT_SECRET=None)
    assert result.returncode == 2
    assert result.fake is None  # manage.py never runs
    assert "STRAVA_CLIENT_SECRET: FALTA" in result.stdout
    assert "STRAVA_CLIENT_ID: definida" in result.stdout and "STRAVA_REFRESH_TOKEN: definida" in result.stdout
    output = result.stdout + result.stderr
    assert not any(secret in output for secret in SECRETS + ["demo"])


def test_helper_check_runs_manage_check_with_local_settings(helper):
    result = helper("check")
    assert result.returncode == 0, result.stderr
    assert "FALTA" not in result.stdout
    assert result.fake["argv"] == ["manage.py", "check", "--settings=strava_app.settings_local"]
    assert result.fake["cwd"] == str(ROOT)
    assert result.fake["dsm"] == "strava_app.settings_local"  # not manage.py's default, strava_app.settings
    assert result.fake["db"] == ["127.0.0.1", "55433", "stravagancia_test_demo"]
    assert visible_keys(result.fake) == BASE_KEYS | set(SYNTHETIC) | {"GARAGE_STRAVA_USER"}
    assert not any(secret in result.stdout + result.stderr for secret in SECRETS)


def test_helper_forwards_exactly_the_allowed_keys(helper):
    optional = {"GARAGE_SYNC_TOKEN": "synthetic-sync-token-" + "x" * 32, "STRAVA_WEBHOOK_SUBSCRIPTION_ID": "123"}
    serve = helper("serve", **optional)
    assert serve.returncode == 0, serve.stderr
    assert serve.fake["argv"] == ["manage.py", "runserver", "--settings=strava_app.settings_local", "127.0.0.1:8767",
                                  "--noreload", "--insecure"]
    assert "http://127.0.0.1:8767/garage/" in serve.stdout
    assert visible_keys(serve.fake) == BASE_KEYS | set(SYNTHETIC) | {"GARAGE_STRAVA_USER"} | set(optional)
    assert serve.fake["db"] == ["127.0.0.1", "55433", "stravagancia_test_demo"]
    port = helper("serve", "8777")
    assert port.fake["argv"][3] == "127.0.0.1:8777"
    run = helper("run", "garage_probikegarage_verify", "dump.json", "--owner", "2")
    assert run.returncode == 0, run.stderr
    assert run.fake["argv"] == ["manage.py", "garage_probikegarage_verify", "--settings=strava_app.settings_local",
                                "dump.json", "--owner", "2"]
    assert visible_keys(run.fake) == BASE_KEYS | set(SYNTHETIC) | {"GARAGE_STRAVA_USER"}
    for args in [("run", "migrate", "--settings=strava_app.settings_local"), ("run", "manage.py", "migrate")]:
        same = helper(*args)
        assert same.fake["argv"] == ["manage.py", "migrate", "--settings=strava_app.settings_local"]
    # R1: a «--» never leaves the settings behind it (Django's pre-parse stops there).
    dash = helper("run", "migrate", "--", "garage")
    assert dash.fake["argv"] == ["manage.py", "migrate", "--settings=strava_app.settings_local", "--", "garage"]
    assert dash.fake["dsm"] == "strava_app.settings_local"


@pytest.mark.parametrize("args", [
    ("run", "-m", "pytest"), ("run", "test"), ("run", "pytest"), ("run", "shell"), ("run", "dbshell"),
    ("run", "manage.py", "test"), ("run", "runserver", "0.0.0.0:8767"), ("run",), ("run", "diffsettings"),
    ("run", "diffsettings", "--all"), ("run", "--settings=strava_app.settings_local"),
    ("run", "check", "--settings=strava_app.settings"), ("run", "check", "--settings", "strava_app.settings"),
    ("run", "check", "--sett=strava_app.settings_test"), ("serve", "80"), ("serve", "abc"), ("serve", "8767", "x"),
    ("check", "extra"), ("stop",), (),
])
def test_helper_refusals(helper, args):
    result = helper(*args)
    assert result.returncode == 2
    assert result.fake is None


def test_helper_serve_and_run_require_the_strava_variables(helper):
    for args in [("serve",), ("run", "check")]:
        result = helper(*args, STRAVA_REFRESH_TOKEN="")
        assert result.returncode == 2 and result.fake is None
        assert "STRAVA_REFRESH_TOKEN: FALTA" in result.stdout


def test_helper_requires_the_demo_state(helper, tmp_path):
    for action in [("check",), ("serve",), ("run", "check")]:
        result = helper(*action, GARAGE_DEMO_STATE=str(tmp_path / "missing.json"))
        assert result.returncode == 2 and result.fake is None
        assert "garage_demo_pg.py start" in result.stderr
    other = tmp_path / "other-state.json"
    other.write_text(json.dumps({"root": "/private/tmp/x", "port": 55434}))
    result = helper("check", GARAGE_DEMO_STATE=str(other))
    assert result.returncode == 2 and result.fake is None


# 6b. garage-048: the helper also takes the three Strava variables from .env (spec §7, D4'.1–D4'.7).
# Synthetic files are never called .env: this pytest process may not open such a file (isolation).

FILE_STRAVA = {"STRAVA_CLIENT_ID": "file-local-id-4801", "STRAVA_CLIENT_SECRET": "file-local-secret-4802",
               "STRAVA_REFRESH_TOKEN": "file-local-refresh-4803"}
# What the real .env also holds (production database, Neon, cron, the legacy access token) and
# names the helper or its child read elsewhere: none of it may reach the child or change the helper.
FILE_FOREIGN = {"DB_HOST": "file-production-4804.invalid", "DB_PASSWORD": "file-db-4805",
                "NEON_PASSWORD": "file-neon-4806", "CRONJOB_API_KEY": "file-cron-4807",
                "STRAVA_ACCESS_TOKEN": "file-access-4808",
                "DATABASE_URL": "postgres://remote:file-url-4809@production.invalid/production",
                "SECRET_KEY": "file-key-4810", "GARAGE_STRAVA_USER": "file-user-4811",
                "GARAGE_SYNC_TOKEN": "file-sync-4812-" + "y" * 32, "STRAVA_WEBHOOK_SUBSCRIPTION_ID": "file-sub-4813",
                "STRAVA_WEBHOOK_VERIFY_TOKEN": "file-webhook-4814", "DJANGO_SETTINGS_MODULE": "strava_app.settings",
                "TEST_DB_PORT": "5432", "TEST_DB_NAME": "stravagancia_test_file", "GARAGE_TEST_PYTHON": "/usr/bin/false",
                "GARAGE_DEMO_STATE": "/nonexistent-file-4815.json", "GARAGE_LOCAL_ENV_FILE": "/nonexistent-file-4816",
                "PYTHONPATH": "/nonexistent-file-4817", "PATH": "/nonexistent-file-4818", "LC_ALL": "file-locale-4819"}
FILE_SECRETS = list(FILE_STRAVA.values()) + [v for v in FILE_FOREIGN.values() if "file-" in v]
NO_EXPORT = {name: None for name in FILE_STRAVA}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def write_env_file(tmp_path, text, name="strava.env"):
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return str(path)


def env_file_lines(values):
    return "".join(f"{key}={value}\n" for key, value in values.items())


def test_helper_tests_never_read_the_real_env_file(helper, tmp_path):
    """D4'.7: by default the fixture's helper looks at a missing file inside tmp_path, never at the repository's."""
    result = helper("check")
    assert result.returncode == 0, result.stderr
    assert helper.env_file.parent == tmp_path and not helper.env_file.exists()
    # check says, in one line, that the file it was given does not exist: it looked there.
    assert len([line for line in result.stdout.splitlines() if str(helper.env_file) in line]) == 1
    assert str(ROOT / ".env") not in result.stdout + result.stderr
    # And the fixture refuses to launch the helper towards the real file, before running anything. Should
    # that guard break, an unknown action and no demo state still stop the helper before it reads a .env.
    for value in [None, "", str(ROOT / ".env"), ".env", str(ROOT / "tools" / ".." / ".env")]:
        with pytest.raises(AssertionError, match="real .env"):
            helper("not-an-action", GARAGE_LOCAL_ENV_FILE=value, GARAGE_DEMO_STATE=str(tmp_path / "no-demo.json"))


def test_a_direct_launch_of_the_helper_must_pin_a_synthetic_env_file(tmp_path, monkeypatch):
    """D4'.7 at run time, not only in the fixtures: from this pytest process, launching the helper without
    GARAGE_LOCAL_ENV_FILE as an absolute path inside the temporary directory is refused before it starts.

    Every launch here is an unknown action with no demo state: even without the guard, the helper
    would stop before reading any .env.
    """
    monkeypatch.delenv("GARAGE_LOCAL_ENV_FILE", raising=False)
    monkeypatch.setenv("GARAGE_DEMO_STATE", str(tmp_path / "no-demo.json"))  # for the inherited environment
    base = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path),
            "GARAGE_DEMO_STATE": str(tmp_path / "no-demo.json")}
    argv = [sys.executable, str(HELPER), "not-an-action"]
    into_repo = tmp_path / "link.env"
    into_repo.symlink_to(ROOT / "no-such-directory-4841" / "strava.env")
    for env in [base, None, dict(base, GARAGE_LOCAL_ENV_FILE=""), dict(base, GARAGE_LOCAL_ENV_FILE=str(ROOT / ".env")),
                dict(base, GARAGE_LOCAL_ENV_FILE="missing-strava.env"),
                dict(base, GARAGE_LOCAL_ENV_FILE=str(Path(tempfile.gettempdir()) / ".." / "strava.env")),
                dict(base, GARAGE_LOCAL_ENV_FILE=str(into_repo))]:
        with pytest.raises(RuntimeError, match="real .env"):
            subprocess.run(argv, cwd=tmp_path, env=env, capture_output=True, timeout=60)
    with pytest.raises(RuntimeError, match="real .env"):
        subprocess.run(" ".join(map(str, argv)), shell=True, cwd=tmp_path, env=base, capture_output=True, timeout=60)
    with pytest.raises(RuntimeError, match="real .env"):
        os.system(" ".join(map(str, argv)))
    allowed = subprocess.run(argv, cwd=tmp_path, env=dict(base, GARAGE_LOCAL_ENV_FILE=str(tmp_path / "missing.env")),
                             capture_output=True, text=True, timeout=60)
    assert allowed.returncode == 2 and "Uso:" in allowed.stderr


def test_every_test_module_that_runs_the_helper_sets_its_env_file():
    """D4'.7, for later modules too: whoever launches the helper pins GARAGE_LOCAL_ENV_FILE and installs the
    run-time guard (so it holds when that module runs alone)."""
    modules = []
    for directory, subdirectories, files in os.walk(ROOT):
        subdirectories[:] = [d for d in subdirectories
                             if not d.startswith(".") and d not in {"node_modules", "staticfiles", "metabase-data"}]
        for name in files:
            if name == "tests.py" or (name.startswith("tests_") and name.endswith(".py")):
                text = (Path(directory) / name).read_text(encoding="utf-8")
                if "garage_local_strava" in text:
                    modules.append(name)
                    assert "GARAGE_LOCAL_ENV_FILE" in text, name + " runs the helper without GARAGE_LOCAL_ENV_FILE"
                    assert "install_helper_launch_guard()" in text, name + " runs the helper without the guard"
    assert {"tests_local_strava.py", "tests_local_strava_review.py"} <= set(modules)


def test_helper_takes_only_the_three_strava_variables_from_the_env_file(helper, tmp_path):
    """D4'.1: nothing else of the file reaches the child or changes the helper (Python, demo state, database)."""
    env_file = write_env_file(tmp_path, "# synthetic copy of a .env\n" + env_file_lines(FILE_FOREIGN)
                              + env_file_lines(FILE_STRAVA))
    expected_keys = BASE_KEYS | set(FILE_STRAVA)
    check = helper("check", GARAGE_LOCAL_ENV_FILE=env_file, GARAGE_STRAVA_USER=None, **NO_EXPORT)
    assert check.returncode == 0, check.stderr
    for name in FILE_STRAVA:
        assert f"{name}: definida (de .env)" in check.stdout
    assert "FALTA" not in check.stdout
    serve = helper("serve", GARAGE_LOCAL_ENV_FILE=env_file, GARAGE_STRAVA_USER=None, **NO_EXPORT)
    run = helper("run", "garage_probikegarage_verify", "dump.json", GARAGE_LOCAL_ENV_FILE=env_file,
                 GARAGE_STRAVA_USER=None, **NO_EXPORT)
    for result in (check, serve, run):
        assert result.returncode == 0, result.stderr
        assert result.fake is not None  # GARAGE_TEST_PYTHON and GARAGE_DEMO_STATE of the file were ignored
        assert visible_keys(result.fake) == expected_keys
        assert "GARAGE_LOCAL_ENV_FILE" not in result.fake["keys"]
        assert result.fake["strava"] == {name: digest(value) for name, value in FILE_STRAVA.items()}
        assert result.fake["dsm"] == "strava_app.settings_local"
        assert result.fake["db"] == ["127.0.0.1", "55433", "stravagancia_test_demo"]
        assert not any(secret in result.stdout + result.stderr for secret in FILE_SECRETS)
    assert serve.fake["argv"][:4] == ["manage.py", "runserver", "--settings=strava_app.settings_local",
                                      "127.0.0.1:8767"]


def test_exported_variables_win_over_the_env_file(helper, tmp_path):
    """D4'.2: exported and not empty wins; otherwise the file's, if not empty; otherwise missing."""
    env_file = write_env_file(tmp_path, env_file_lines(FILE_STRAVA))
    exported_id = "exported-local-id-4821"
    mixed = helper("check", GARAGE_LOCAL_ENV_FILE=env_file, STRAVA_CLIENT_ID=exported_id, STRAVA_CLIENT_SECRET="",
                   STRAVA_REFRESH_TOKEN="   ")
    assert mixed.returncode == 0, mixed.stderr
    assert "STRAVA_CLIENT_ID: definida (exportada)" in mixed.stdout
    assert "STRAVA_CLIENT_SECRET: definida (de .env)" in mixed.stdout
    assert "STRAVA_REFRESH_TOKEN: definida (de .env)" in mixed.stdout
    assert mixed.fake["strava"] == {"STRAVA_CLIENT_ID": digest(exported_id),
                                    "STRAVA_CLIENT_SECRET": digest(FILE_STRAVA["STRAVA_CLIENT_SECRET"]),
                                    "STRAVA_REFRESH_TOKEN": digest(FILE_STRAVA["STRAVA_REFRESH_TOKEN"])}
    exported = helper("run", "check", GARAGE_LOCAL_ENV_FILE=env_file)
    assert exported.returncode == 0, exported.stderr
    assert exported.fake["strava"] == {name: digest(value) for name, value in SYNTHETIC.items()}
    checked = helper("check", GARAGE_LOCAL_ENV_FILE=env_file)
    for name in SYNTHETIC:
        assert f"{name}: definida (exportada)" in checked.stdout
    # Empty in the file and empty (or absent) in the shell: missing, and nothing runs.
    partial = write_env_file(tmp_path, "STRAVA_CLIENT_ID=file-local-id-4801\nSTRAVA_CLIENT_SECRET=\n", "partial.env")
    for action in [("check",), ("serve",), ("run", "check")]:
        result = helper(*action, GARAGE_LOCAL_ENV_FILE=partial, STRAVA_CLIENT_ID=None, STRAVA_CLIENT_SECRET="",
                        STRAVA_REFRESH_TOKEN=None)
        assert result.returncode == 2 and result.fake is None
        assert "STRAVA_CLIENT_ID: definida (de .env)" in result.stdout
        assert "STRAVA_CLIENT_SECRET: FALTA" in result.stdout and "STRAVA_REFRESH_TOKEN: FALTA" in result.stdout
        assert not any(secret in result.stdout + result.stderr for secret in FILE_SECRETS)


@pytest.mark.parametrize("text,expected", [
    ("STRAVA_REFRESH_TOKEN=tok-4831\n", "tok-4831"),
    ("export STRAVA_REFRESH_TOKEN=tok-4831\n", "tok-4831"),
    ("  export \tSTRAVA_REFRESH_TOKEN = tok-4831  \n", "tok-4831"),
    ('STRAVA_REFRESH_TOKEN="tok 4831"\n', "tok 4831"),
    ("STRAVA_REFRESH_TOKEN='tok#4831'\n", "tok#4831"),
    # Inside quotes nothing is a comment and nothing is stripped (as python-dotenv).
    ('STRAVA_REFRESH_TOKEN="tok #4831"\n', "tok #4831"),
    ("STRAVA_REFRESH_TOKEN='tok #4831' # renewed by hand\n", "tok #4831"),
    ('STRAVA_REFRESH_TOKEN="  tok-4831  "\n', "  tok-4831  "),
    ('export STRAVA_REFRESH_TOKEN="tok-4831" # renewed by hand\n', "tok-4831"),
    ("STRAVA_REFRESH_TOKEN=tok-4831 # renewed by hand\n", "tok-4831"),
    ("STRAVA_REFRESH_TOKEN=tok-4831\t# renewed by hand\n", "tok-4831"),
    ("STRAVA_REFRESH_TOKEN=tok#4831\n", "tok#4831"),
    ("STRAVA_REFRESH_TOKEN=tok=4831\n", "tok=4831"),
    ("STRAVA_REFRESH_TOKEN=tok-4831\r\n", "tok-4831"),
    ('STRAVA_REFRESH_TOKEN="tok-4831"\r\n', "tok-4831"),
    ("# old Mac line ends\rSTRAVA_REFRESH_TOKEN=tok-4831\rSTRAVA_ACCESS_TOKEN=other-4833\r", "tok-4831"),
    ("﻿STRAVA_REFRESH_TOKEN=tok-4831\n", "tok-4831"),
    ("STRAVA_REFRESH_TOKEN=tok-4831", "tok-4831"),
    ("STRAVA_REFRESH_TOKEN=old-4830\nSTRAVA_REFRESH_TOKEN=tok-4831\n", "tok-4831"),
    ('STRAVA_REFRESH_TOKEN=tok-4831\nSTRAVA_REFRESH_TOKEN="broken-4832\n', "tok-4831"),
    ("STRAVA_REFRESH_TOKEN=tok-4831\nSTRAVA_REFRESH_TOKEN broken-4832\n", "tok-4831"),
    # No process environment can hold a NUL: such a value is a bad line, not a traceback at launch.
    ("STRAVA_REFRESH_TOKEN=tok-4831\nSTRAVA_REFRESH_TOKEN=broken-4832\x00tail-4833\n", "tok-4831"),
    ('STRAVA_REFRESH_TOKEN="broken-4832\x00tail-4833"\n', None),
    ("STRAVA_REFRESH_TOKEN=old-4830\nSTRAVA_REFRESH_TOKEN=\n", None),
    ("# STRAVA_REFRESH_TOKEN=commented-4832\n", None),
    ("STRAVA_REFRESH_TOKEN=\n", None),
    ("STRAVA_REFRESH_TOKEN=   \n", None),
    ("STRAVA_REFRESH_TOKEN= # comment-4832\n", None),
    ('STRAVA_REFRESH_TOKEN=""\n', None),
    ("STRAVA_REFRESH_TOKEN='   '\n", None),
    ('STRAVA_REFRESH_TOKEN="broken-4832\n', None),
    ("STRAVA_REFRESH_TOKEN='broken-4832\"\n", None),
    ('STRAVA_REFRESH_TOKEN="broken-4832" trailing-4833\n', None),
    ("STRAVA_REFRESH_TOKEN broken-4832\n", None),
    ("strava_refresh_token=broken-4832\n", None),
    ("STRAVA_REFRESH_TOKEN_OLD=broken-4832\nXSTRAVA_REFRESH_TOKEN=broken-4834\n", None),
    ("export\n=broken-4832\n\n   \n#\n", None),
])
def test_env_file_format(helper, tmp_path, text, expected):
    """D4'.4: KEY=value, optional export, paired quotes, CRLF, comments, last one wins; bad lines ignored, unseen."""
    others = {k: v for k, v in FILE_STRAVA.items() if k != "STRAVA_REFRESH_TOKEN"}
    env_file = write_env_file(tmp_path, text + "\n" + env_file_lines(others))
    result = helper("check", GARAGE_LOCAL_ENV_FILE=env_file, **NO_EXPORT)
    output = result.stdout + result.stderr
    assert "Traceback" not in output
    assert not any(marker in output for marker in ("4830", "4831", "4832", "4833", "4834")), output
    assert "STRAVA_CLIENT_ID: definida (de .env)" in result.stdout
    if expected is None:
        assert result.returncode == 2 and result.fake is None
        assert "STRAVA_REFRESH_TOKEN: FALTA" in result.stdout
    else:
        assert result.returncode == 0, output
        assert "STRAVA_REFRESH_TOKEN: definida (de .env)" in result.stdout
        assert result.fake["strava"]["STRAVA_REFRESH_TOKEN"] == digest(expected)


@pytest.mark.parametrize("kind", ["missing", "directory", "unreadable", "dangling-link", "fifo"])
def test_env_file_missing_or_unreadable_counts_as_empty(helper, tmp_path, kind):
    """D4'.5: as if it had no values (the exported ones count); check says so in one line, without a traceback.

    Only a regular file is read: a FIFO without a writer would block the helper forever (and a
    device such as /dev/zero would never end; not tested: a regression would exhaust memory).
    """
    path = tmp_path / "strava-source"
    if kind == "directory":
        path.mkdir()
    elif kind == "fifo":
        os.mkfifo(path)
    elif kind == "unreadable":
        path.write_text(env_file_lines(FILE_STRAVA))
        path.chmod(0)
        if os.access(path, os.R_OK):
            pytest.skip("this user can read a file with mode 000")
    elif kind == "dangling-link":
        path.symlink_to(tmp_path / "nowhere.env")
    exported = helper("check", GARAGE_LOCAL_ENV_FILE=str(path))
    missing = helper("check", GARAGE_LOCAL_ENV_FILE=str(path), **NO_EXPORT)
    serve = helper("serve", GARAGE_LOCAL_ENV_FILE=str(path), **NO_EXPORT)
    assert exported.returncode == 0, exported.stderr
    assert exported.fake["strava"] == {name: digest(value) for name, value in SYNTHETIC.items()}
    for name in SYNTHETIC:
        assert f"{name}: definida (exportada)" in exported.stdout
        assert f"{name}: FALTA" in missing.stdout and f"{name}: FALTA" in serve.stdout
    assert missing.returncode == 2 and missing.fake is None
    assert serve.returncode == 2 and serve.fake is None
    # One line about the file; with variables missing it is shown too (next to the list of what is missing).
    note = [line for line in exported.stdout.splitlines() if str(path) in line]
    assert len(note) == 1
    assert note[0] in missing.stdout.splitlines() and note[0] in serve.stdout.splitlines()
    for result in (exported, missing, serve):
        output = result.stdout + result.stderr
        assert "Traceback" not in output and "Error" not in output
        assert not any(secret in output for secret in FILE_SECRETS)
    if kind == "unreadable":
        path.chmod(0o600)


def test_messages_no_longer_say_never_from_env(helper):
    """D4'.6: .env is now a valid source for the helper; the messages say where the values may come from."""
    result = helper("check", STRAVA_CLIENT_SECRET=None)
    assert result.returncode == 2
    assert "nunca desde .env" not in result.stdout + result.stderr
    assert str(helper.env_file) in result.stdout
    child_result = child("import strava_app.settings_local", STRAVA_REFRESH_TOKEN=None)
    assert child_result.returncode != 0 and "STRAVA_REFRESH_TOKEN" in child_result.stderr
    assert "never from .env" not in child_result.stderr


# 7. The suite never runs with the local settings.

def test_suite_rejects_local_settings():
    with pytest.raises(RuntimeError, match="require strava_app.settings_test"):
        validate_settings_choice("strava_app.settings_local")
