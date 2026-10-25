"""Regression tests of process bootstrap, network guards and PostgreSQL."""
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parent


def child(code, **overrides):
    env = dict(os.environ)
    env.pop("DJANGO_SETTINGS_MODULE", None)
    env.update(overrides)
    return subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


def test_bootstrap_ignores_production_environment():
    result = child('''
import json, os, sys
from strava_app import settings_test as s
from strava_integration import utils
assert 'strava_app.settings' not in sys.modules
assert 'DATABASE_URL' not in os.environ
assert not any(k.startswith(('DB_', 'PG')) for k in os.environ)
assert utils.STRAVA_CLIENT_SECRET == 'synthetic-secret'
print(json.dumps(s.DATABASES))
''', DATABASE_URL="postgres://remote:fake@production.invalid/production",
        DB_HOST="production.invalid", DB_NAME="production", DB_PASSWORD="fake",
        PGHOSTADDR="203.0.113.1", PGSERVICE="production", PGOPTIONS="-c search_path=production",
        STRAVA_CLIENT_SECRET="fake-production-secret", SECRET_KEY="fake-production-key")
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)["default"]
    assert config["ENGINE"] == "django.db.backends.postgresql"
    assert config["HOST"] in {"127.0.0.1", "::1"}
    assert config["TEST"]["NAME"].startswith("test_stravagancia_test")


def test_garage_strava_environment_absent_under_pytest():
    """Target of the next test; it only proves something when the shell exported the keys."""
    from django.conf import settings
    assert settings.GARAGE_STRAVA_USER == ""
    assert not {"GARAGE_STRAVA_USER", "GARAGE_SYNC_TOKEN"} & set(os.environ)


def test_pytest_drops_garage_strava_environment_that_the_demo_reads():
    env = {"GARAGE_STRAVA_USER": "demo", "GARAGE_SYNC_TOKEN": "synthetic-token"}
    result = child('''
import os, pytest
os.environ.pop("PYTEST_ADDOPTS", None)
raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider",
                              "tests_test_environment.py::test_garage_strava_environment_absent_under_pytest"]))
''', **env)
    assert result.returncode == 0, result.stdout + result.stderr
    # Outside pytest (the demo's runserver) settings_test reads what the demo helper passes.
    result = child('''
import os
os.environ.pop("PYTEST_VERSION", None)
from strava_app import settings_test as s
print(s.GARAGE_STRAVA_USER)
''', **env)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "demo"


@pytest.mark.parametrize("key,value", [
    ("TEST_DB_HOST", "production.invalid"), ("TEST_DB_HOST", "localhost"),
    ("TEST_DB_HOST", ""), ("TEST_DB_HOST", "/tmp"),
    ("TEST_DB_HOST", "127.0.0.1,production.invalid"),
    ("TEST_DB_PORT", "0"), ("TEST_DB_PORT", "65536"), ("TEST_DB_PORT", "abc"),
    ("TEST_DB_NAME", "production"), ("TEST_DB_NAME", "stravagancia_test;drop"),
    ("TEST_DB_USER", "user host=remote"),
])
def test_invalid_database_configuration_rejected_before_django(key, value):
    result = child('''
import sys
try:
    import strava_app.settings_test
except RuntimeError:
    assert 'django' not in sys.modules
    print('rejected')
else:
    raise AssertionError('unsafe configuration accepted')
''', **{key: value})
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "rejected"


@pytest.mark.parametrize("args,env", [
    (["--ds=strava_app.settings"], {}),
    (["--ds", "strava_app.settings"], {}),
    (["-o", "DJANGO_SETTINGS_MODULE=strava_app.settings"], {}),
    ([], {"DJANGO_SETTINGS_MODULE": "strava_app.settings"}),
    ([], {"PYTEST_ADDOPTS": "--ds=strava_app.settings"}),
    (["test_strava_connection.py"], {}),
    (["-o", "addopts=", "--ds=strava_app.settings"], {}),
    (["-o", "addopts="], {"DJANGO_SETTINGS_MODULE": "strava_app.settings"}),
    (["--ds=strava_app.settings"], {"PYTEST_ADDOPTS": "-p no:test_support.pytest_plugin"}),
])
def test_pytest_rejects_unsafe_bootstrap(args, env):
    result = child('''
import pytest
raise SystemExit(pytest.main(%r))
''' % (["--collect-only", "-q"] + args), **env)
    assert result.returncode != 0
    assert "require strava_app.settings_test" in result.stderr or "manual API script" in result.stderr
    assert "load_dotenv" not in result.stderr


@pytest.mark.parametrize("args", [[], ["--settings=strava_app.settings"], ["--settings", "strava_app.settings"],
                                  ["--sett=strava_app.settings"], ["--sett", "strava_app.settings"]])
def test_manage_test_bootstraps_safely(args):
    # Replace execution with a probe: never create a database in the child.
    result = child('''
import sys
from unittest.mock import patch
sys.argv = ['manage.py', 'test'] + %r
def probe(argv):
    from django.conf import settings
    assert settings.SETTINGS_MODULE == 'strava_app.settings_test'
    assert settings.DATABASES['default']['HOST'] in {'127.0.0.1', '::1'}
    print('safe')
with patch('django.core.management.execute_from_command_line', probe):
    import manage
    manage.main()
''' % args)
    if args:
        assert result.returncode != 0
        assert "alternative settings are rejected" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "safe"


def test_http_and_other_network_blocked_before_collection():
    result = child('''
from test_support.isolation import install
install()
import requests, urllib.request, socket
calls = [lambda: requests.get('https://example.invalid'),
         lambda: requests.Session().get('http://127.0.0.1:80'),
         lambda: urllib.request.urlopen('http://127.0.0.1:80'),
         lambda: urllib.request.urlopen('https://example.invalid'),
         lambda: socket.socket().connect(('203.0.113.1', 443)),
         lambda: socket.socket().connect_ex(('127.0.0.1', 80))]
for call in calls:
    try: call()
    except RuntimeError: pass
    else: raise AssertionError('network escaped')
print('blocked')
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "blocked"


def test_http_mocks_work():
    import requests
    with patch("requests.post", return_value=Mock(status_code=200)):
        assert requests.post("https://example.invalid").status_code == 200


def test_dotenv_loading_disabled_and_env_open_forbidden(tmp_path):
    import dotenv
    assert dotenv.load_dotenv(tmp_path / ".env") is False
    assert dotenv.dotenv_values(tmp_path / ".env") == {}
    for mode in ["r", "w", "a"]:
        with pytest.raises(RuntimeError, match="cannot read or write .env"):
            (tmp_path / ".env").open(mode)


def test_mocked_token_refresh_cannot_write_env(tmp_path):
    from strava_integration import utils
    response = Mock()
    response.json.return_value = {"access_token": "synthetic-new", "refresh_token": "synthetic-new-refresh"}
    with patch.object(utils, "_ENV_FILE", str(tmp_path / ".env")), \
            patch("os.path.exists", return_value=True), patch.object(utils.requests, "post", return_value=response):
        with pytest.raises(RuntimeError, match="cannot read or write .env"):
            utils.refresh_access_token()


@pytest.mark.parametrize("extra", [
    {"host": "production.invalid"}, {"hostaddr": "203.0.113.1"},
    {"service": "production"}, {"dbname": "production"},
    {"options": "-c search_path=production"}, {"port": "5432"},
])
def test_libpq_rejects_connection_overrides(extra):
    import psycopg2
    from django.conf import settings
    cfg = settings.DATABASES["default"]
    params = {"host": cfg["HOST"], "port": cfg["PORT"], "dbname": cfg["NAME"], "user": cfg["USER"]}
    if "port" in extra:
        extra = {"port": "5433" if str(cfg["PORT"]) == "5432" else "5432"}
    params.update(extra)
    with pytest.raises(RuntimeError, match="dedicated local test configuration"):
        psycopg2.connect(**params)


@pytest.mark.django_db
def test_real_postgresql_database_is_dedicated_and_writable():
    from django.db import connection
    assert connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_database(), host(inet_server_addr())")
        name, address = cursor.fetchone()
        assert name.startswith("test_stravagancia_test")
        assert address in {"127.0.0.1", "::1"}
        cursor.execute("CREATE TEMP TABLE isolation_probe (id integer PRIMARY KEY)")
        cursor.execute("INSERT INTO isolation_probe VALUES (1)")
        cursor.execute("SELECT count(*) FROM isolation_probe")
        assert cursor.fetchone()[0] == 1


@pytest.mark.parametrize("key", ["PGHOSTADDR", "PGSERVICE", "PGOPTIONS"])
def test_reintroduced_libpq_environment_rejected(monkeypatch, key):
    import psycopg2
    from django.conf import settings
    cfg = settings.DATABASES["default"]
    monkeypatch.setenv(key, "synthetic-unsafe")
    with pytest.raises(RuntimeError, match="dedicated local test configuration"):
        psycopg2.connect(host=cfg["HOST"], port=cfg["PORT"], dbname=cfg["NAME"], user=cfg["USER"])


def test_libpq_validation_preserves_allowed_connections_and_dsn_precedence():
    result = child('''
import psycopg2
calls = []
def backend(*args, **kwargs):
    calls.append((args, kwargs))
    return 'connected'
psycopg2.connect = backend
from test_support.isolation import install, database_config
install()
cfg = database_config()
params = dict(host=cfg['HOST'], port=cfg['PORT'], dbname=cfg['NAME'], user=cfg['USER'])
assert psycopg2.connect(**params) == 'connected'
# kwargs override the DSN exactly as libpq/psycopg2 expect.
assert psycopg2.connect('host=production.invalid', **params) == 'connected'
for dsn in ['postgresql://user:fake@production.invalid/production',
            'host=127.0.0.1,production.invalid dbname=stravagancia_test',
            'hostaddr=127.0.0.1', 'service=synthetic']:
    try: psycopg2.connect(dsn, port=cfg['PORT'], dbname=cfg['NAME'], user=cfg['USER'])
    except RuntimeError: pass
    else: raise AssertionError('unsafe DSN accepted')
from django.conf import settings
from django.db.backends.postgresql.base import DatabaseWrapper
wrapper = DatabaseWrapper(settings.DATABASES['default'])
actual_params = wrapper.get_connection_params()
assert 'cursor_factory' in actual_params
assert psycopg2.connect(**actual_params) == 'connected'
remote_cfg = dict(settings.DATABASES['default'], HOST='production.invalid')
remote = DatabaseWrapper(remote_cfg, alias='remote').get_connection_params()
try: psycopg2.connect(**remote)
except RuntimeError: pass
else: raise AssertionError('remote Django alias accepted')
assert len(calls) == 3
print('safe')
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "safe"


def test_dns_guard_rejects_before_resolver():
    result = child('''
import socket
calls = []
def resolver(*args, **kwargs):
    calls.append(args)
    return ['synthetic-resolution']
socket.getaddrinfo = resolver
from test_support.isolation import install, database_config
install()
cfg = database_config()
try: socket.getaddrinfo('example.invalid', 443)
except RuntimeError: pass
else: raise AssertionError('external DNS accepted')
assert calls == []
assert socket.getaddrinfo(cfg['HOST'], int(cfg['PORT'])) == ['synthetic-resolution']
assert len(calls) == 1
print('safe')
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "safe"


def test_manage_non_test_command_keeps_normal_bootstrap():
    result = child('''
import os, sys
from unittest.mock import patch
sys.argv = ['manage.py', 'shell', 'test']
def probe(argv):
    assert os.environ['DJANGO_SETTINGS_MODULE'] == 'strava_app.settings'
    assert 'test_support.isolation' not in sys.modules
    print('normal')
with patch('django.core.management.execute_from_command_line', probe):
    import manage
    manage.main()
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "normal"


@pytest.mark.parametrize("overrides", [
    {"TEST_DB_HOST": "::1"}, {"TEST_DB_PORT": "1"}, {"TEST_DB_PORT": "65535"},
    {"TEST_DB_NAME": "stravagancia_test_ci123"},
])
def test_valid_configuration_boundaries(overrides):
    result = child("from strava_app.settings_test import DATABASES; print('safe')", **overrides)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "safe"


def test_local_postgresql_socket_connections_reach_backend():
    result = child('''
import socket
calls = []
def backend(sock, address):
    calls.append(address)
    return 'connected'
socket.socket.connect = backend
socket.socket.connect_ex = backend
from test_support.isolation import install, database_config
install()
cfg = database_config()
address = (cfg['HOST'], int(cfg['PORT']))
sock = socket.socket()
assert sock.connect(address) == 'connected'
assert sock.connect_ex(address) == 'connected'
assert calls == [address, address]
print('safe')
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "safe"



def test_documented_module_command_collects_suite_in_real_subprocess():
    env = dict(os.environ)
    # The documented module invocation must work without an injected import path.
    env.pop("PYTHONPATH", None)
    env.pop("PYTEST_ADDOPTS", None)
    result = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"],
                            cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "strava_integration/tests.py::test_athlete_str" in result.stdout
    assert "strava_integration/tests_renaming.py::test_is_generic_name" in result.stdout
    assert "tests_test_environment.py::test_documented_module_command" in result.stdout
    assert "test_strava_connection.py::" not in result.stdout
