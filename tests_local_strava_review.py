"""garage-044, adversarial review: probes of strava_app.settings_local and its helper.

One test per finding of the spec's section 5 (test_r044_n). A test that fails with the
current code demonstrates a defect; the gap test (marked as such) passes and pins a
protection nobody pinned. Synthetic values only, children with an explicit environment
(PYTHON_DOTENV_DISABLED=1 as a safety net) and fake sockets installed before the local
settings, so no probe can reach a real host even if a guard regressed.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from tests_local_strava import install_helper_launch_guard

install_helper_launch_guard()  # D4'.7: no launch of the helper from this process may read the real .env

ROOT = Path(__file__).resolve().parent
HELPER = ROOT / "tools" / "handoff" / "garage_local_strava.py"
SYNTHETIC = {"STRAVA_CLIENT_ID": "synthetic-review-id-5811", "STRAVA_CLIENT_SECRET": "synthetic-review-secret-5812",
             "STRAVA_REFRESH_TOKEN": "synthetic-review-refresh-5813"}
SYNC_TOKEN = "synthetic-review-sync-token-" + "5" * 32
# Installed before strava_app.settings_local: its guards wrap these fakes, never the real resolver or sockets.
FAKE_NETWORK = '''
import socket
resolved, connected = [], []
def _resolver(host, port, *args, **kwargs):
    resolved.append((host, port))
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.0.2.10", int(port)))]
def _connect(sock, address):
    connected.append(list(address[:2]))
    raise ConnectionRefusedError("review probe: no real network")
def _connect_ex(sock, address):
    connected.append(list(address[:2]))
    return 111
socket.getaddrinfo = _resolver
socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
'''


def child_env(**overrides):
    env = {k: os.environ[k] for k in ("PATH", "HOME") if k in os.environ}
    env.update({k: v for k, v in os.environ.items() if k.startswith("TEST_DB_")})
    env.update(SYNTHETIC, GARAGE_STRAVA_USER="demo", PYTHON_DOTENV_DISABLED="1")
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def child(code, **overrides):
    return subprocess.run([sys.executable, "-c", FAKE_NETWORK + code], cwd=ROOT, env=child_env(**overrides),
                          capture_output=True, text=True, timeout=60)


def require_synthetic_env_file(env, tmp_path):
    """garage-048: the helper reads the real .env unless GARAGE_LOCAL_ENV_FILE says otherwise; never in a probe."""
    value = env.get("GARAGE_LOCAL_ENV_FILE")
    if not value or not Path(value).resolve().is_relative_to(tmp_path.resolve()):
        raise AssertionError("the helper would read the real .env: set GARAGE_LOCAL_ENV_FILE inside tmp_path")


@pytest.fixture
def review_helper(tmp_path):
    """The helper with a fake GARAGE_TEST_PYTHON that prints its argv and DJANGO_SETTINGS_MODULE.

    GARAGE_LOCAL_ENV_FILE points to a missing file inside tmp_path (garage-048), never to the real .env.
    """
    fake = tmp_path / "fake-python"
    fake.write_text("#!" + sys.executable + "\n" + '''import json, os, sys
print("FAKE " + json.dumps({"argv": sys.argv[1:], "dsm": os.environ.get("DJANGO_SETTINGS_MODULE")}))
''')
    fake.chmod(0o700)
    state = tmp_path / "demo-state.json"
    state.write_text(json.dumps({"root": "/private/tmp/garage018-demo-synthetic", "port": 55433}))
    base = dict(SYNTHETIC, PATH=os.environ.get("PATH", "/usr/bin:/bin"), HOME=str(tmp_path), LANG="C",
                GARAGE_TEST_PYTHON=str(fake), GARAGE_DEMO_STATE=str(state), GARAGE_STRAVA_USER="demo",
                GARAGE_LOCAL_ENV_FILE=str(tmp_path / "missing-strava.env"))

    def run(*args, **extra):
        env = dict(base, **extra)
        require_synthetic_env_file(env, tmp_path)
        result = subprocess.run([sys.executable, str(HELPER), *args], cwd=tmp_path, env=env,
                                capture_output=True, text=True, timeout=60)
        lines = [line[5:] for line in result.stdout.splitlines() if line.startswith("FAKE ")]
        result.fake = json.loads(lines[0]) if lines else None
        return result
    return run


def settings_chosen_by_manage_py(fake):
    """The settings module manage.py would load for that argv and environment (no settings imported here).

    Same pre-parse as django.core.management.ManagementUtility.execute(); without a recognised
    --settings and without DJANGO_SETTINGS_MODULE, manage.py's setdefault picks production.
    """
    from django.core.management.base import CommandParser
    parser = CommandParser(add_help=False, allow_abbrev=False)
    parser.add_argument("--settings")
    parser.add_argument("--pythonpath")
    parser.add_argument("args", nargs="*")
    options, _ = parser.parse_known_args(fake["argv"][2:])
    return options.settings or fake["dsm"] or "strava_app.settings"


# r044_1 (importante): a "--" in `run` turns the appended --settings into a positional argument.

@pytest.mark.parametrize("args", [("run", "check", "--", "garage"), ("run", "check", "garage", "--"),
                                  ("run", "migrate", "--", "garage")])
def test_r044_1_double_dash_never_falls_back_to_production_settings(review_helper, args):
    result = review_helper(*args)
    if result.fake is None:  # refusing "--" is also a valid fix
        assert result.returncode == 2
        return
    assert settings_chosen_by_manage_py(result.fake) == "strava_app.settings_local", result.fake


# r044_2 (importante): a guard trip during token renewal is not a RequestException; with
# GARAGE_LOCAL_DEBUG=1 Django's technical 500 page prints the locals of refresh_access_token().

RENEWAL_500 = '''
import sys
import strava_app.settings_local
import django
django.setup()
from django.core.handlers.exception import response_for_exception
from django.test import RequestFactory
from garage.services.strava_client import StravaClient, StravaError
request = RequestFactory().post("/garage/strava/sync/", HTTP_HOST="127.0.0.1")
try:
    StravaClient().athlete()
except StravaError as error:
    print("HANDLED", error.code)
except Exception as exc:
    response = response_for_exception(request, exc)
    print("RESPONSE", response.status_code, type(exc).__name__)
    print(response.content.decode("utf-8", "replace"))
assert resolved == [] and connected == [], (resolved, connected)  # the guard refused before the fake resolver
'''


def test_r044_2_debug_page_never_shows_the_strava_secrets():
    # Any guard trip does it (macOS system proxy, a redirect to another host); a proxy is the simplest trigger.
    result = child(RENEWAL_500, GARAGE_LOCAL_DEBUG="1", HTTPS_PROXY="http://proxy.invalid:3128")
    assert result.returncode == 0, result.stderr
    assert "HANDLED" in result.stdout or "RESPONSE 500" in result.stdout, result.stdout[:500]
    for name in ("STRAVA_CLIENT_SECRET", "STRAVA_REFRESH_TOKEN"):
        assert SYNTHETIC[name] not in result.stdout + result.stderr, name + " printed in the 500 page"


# r044_3 (menor): with DEBUG off (the default) a 500 leaves no trace on the terminal.

def test_r044_3_server_error_is_logged_on_the_terminal():
    result = child('''
import strava_app.settings_local
import django
django.setup()
from django.core.handlers.exception import response_for_exception
from django.test import RequestFactory
request = RequestFactory().post("/garage/strava/sync/", HTTP_HOST="127.0.0.1")
try:
    raise ZeroDivisionError("review probe 500")
except ZeroDivisionError as exc:
    response = response_for_exception(request, exc)
print("RESPONSE", response.status_code)
''')
    assert result.returncode == 0, result.stderr
    assert "RESPONSE 500" in result.stdout
    assert "ZeroDivisionError" in result.stderr, "the 500 is invisible in the terminal: " + repr(result.stderr[-300:])


# r044_4 (menor): D5 allows any method to www.strava.com, writes included.

def test_r044_4_only_reads_and_token_renewal_reach_strava():
    result = child('''
import json
import strava_app.settings_local
import requests
# Adapted in the fixes (spec §6): the guards raise NetworkDenied, an OSError and RequestException, no longer RuntimeError.
from test_support.local_strava import NetworkDenied
outcome = {}
for method, url in [("GET", "https://www.strava.com/api/v3/athlete"),
                    ("PUT", "https://www.strava.com/api/v3/activities/1")]:
    try:
        requests.request(method, url, json={"name": "probe"} if method == "PUT" else None, timeout=1)
    except NetworkDenied:
        outcome[method] = "blocked"
    except requests.RequestException:
        outcome[method] = "connect attempted"
print(json.dumps({"outcome": outcome, "connected": connected}))
''')
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["outcome"]["GET"] == "connect attempted"  # reads still reach the (fake) socket
    assert data["connected"] == [["192.0.2.10", 443]], data  # the PUT must never open a connection
    assert data["outcome"]["PUT"] == "blocked"


# r044_5 (nit): `run diffsettings` prints GARAGE_SYNC_TOKEN, which the helper forwards.

def test_r044_5_helper_never_prints_the_sync_token(review_helper):
    result = review_helper("run", "diffsettings", GARAGE_SYNC_TOKEN=SYNC_TOKEN)
    if result.fake is None:  # refused
        assert result.returncode == 2
        return
    real = subprocess.run([sys.executable, *result.fake["argv"]], cwd=ROOT,
                          env=child_env(GARAGE_SYNC_TOKEN=SYNC_TOKEN), capture_output=True, text=True, timeout=60)
    assert real.returncode == 0, real.stderr
    assert SYNC_TOKEN not in real.stdout + real.stderr, "diffsettings printed GARAGE_SYNC_TOKEN"


# r044_6 (nit): same cookie name as the settings_test demo, different SECRET_KEY, same django_session table.

def test_r044_6_local_server_and_demo_do_not_log_each_other_out():
    from strava_app import settings_test
    result = child('''
import json
from strava_app import settings_local as s
print(json.dumps([getattr(s, "SESSION_COOKIE_NAME", "sessionid"), s.SECRET_KEY, s.DATABASES["default"]["NAME"]]))
''')
    assert result.returncode == 0, result.stderr
    cookie, key, _ = json.loads(result.stdout)
    demo_cookie = getattr(settings_test, "SESSION_COOKIE_NAME", "sessionid")
    assert cookie != demo_cookie or key == settings_test.SECRET_KEY, (
        "both servers on 127.0.0.1 share the 'sessionid' cookie and the demo's sessions, "
        "but sign them with different keys: logging in on one logs out the other")


# r044_7 (gap, passes): the legacy module is imported only after dotenv is neutralized.

def test_r044_7_legacy_utils_imported_after_dotenv_is_neutralized():
    result = child('''
import sys
assert "strava_integration.utils" not in sys.modules and "dotenv" not in sys.modules
import strava_app.settings_local
import dotenv
from strava_integration import utils
assert utils.load_dotenv is dotenv.load_dotenv and utils.load_dotenv.__name__ == "<lambda>"
print("ordered")
''')
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ordered"


# garage-048 (spec §7, D4'.7): the probes above never let the helper read the real .env.

def test_review_helper_never_reads_the_real_env_file(review_helper, tmp_path):
    result = review_helper("check")
    assert result.returncode == 0, result.stderr
    missing = tmp_path / "missing-strava.env"
    assert not missing.exists()
    assert len([line for line in result.stdout.splitlines() if str(missing) in line]) == 1  # it looked there
    assert str(ROOT / ".env") not in result.stdout + result.stderr
    # Should the guard break, an unknown action and no demo state stop the helper before it reads a .env.
    for value in ["", str(ROOT / ".env"), ".env"]:
        with pytest.raises(AssertionError, match="real .env"):
            review_helper("not-an-action", GARAGE_LOCAL_ENV_FILE=value, GARAGE_DEMO_STATE=str(tmp_path / "no-demo.json"))
