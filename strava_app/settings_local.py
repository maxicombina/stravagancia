"""Local settings for real Strava against local PostgreSQL (garage-044); never production, never tests.

The user runs tools/handoff/garage_local_strava.py, which passes STRAVA_CLIENT_ID,
STRAVA_CLIENT_SECRET and STRAVA_REFRESH_TOKEN from their shell or from .env (garage-048).
Never imports strava_app.settings nor reads .env; the database is the local demo cluster (55433)
unless TEST_DB_* says another loopback one; HTTP only to www.strava.com (GET of the
API and POST of the token renewal). DEBUG is always off: Django's technical 500 page
would print the local variables of the token renewal (the Strava secrets).
"""
import logging
import os
from pathlib import Path

from test_support.local_strava import install_local

# First of all (refuses pytest and any other settings module), before Django or the legacy app.
_DATABASE = install_local()
BASE_DIR = Path(__file__).resolve().parent.parent
# Constant and synthetic: sessions survive a restart; never for deployment.
SECRET_KEY = "synthetic-local-strava-secret-key-never-for-deployment"
DEBUG = False
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
# Not the demo's cookies (settings_test, same 127.0.0.1, another SECRET_KEY): both servers can run side by side.
SESSION_COOKIE_NAME = "garage_local_sessionid"
CSRF_COOKIE_NAME = "garage_local_csrftoken"
INSTALLED_APPS = [
    "unfold", "django.contrib.admin", "django.contrib.auth",
    "django.contrib.contenttypes", "django.contrib.sessions",
    "django.contrib.messages", "django.contrib.staticfiles", "axes", "strava_integration", "garage",
]
AUTHENTICATION_BACKENDS = ["axes.backends.AxesStandaloneBackend", "django.contrib.auth.backends.ModelBackend"]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware", "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware", "axes.middleware.AxesMiddleware",
]
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_PARAMETERS = [["ip_address", "username"]]
AXES_IPWARE_PROXY_COUNT = 1
AXES_IPWARE_META_PRECEDENCE_ORDER = ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"]
ROOT_URLCONF = "strava_app.urls"
TEMPLATES = [{"BACKEND": "django.template.backends.django.DjangoTemplates", "DIRS": [], "APP_DIRS": True,
              "OPTIONS": {"context_processors": ["django.template.context_processors.request",
                  "django.contrib.auth.context_processors.auth", "django.contrib.messages.context_processors.messages"]}}]
WSGI_APPLICATION = "strava_app.wsgi.application"
DATABASES = {"default": _DATABASE}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
GRAFANA_URL = "http://localhost:3001"
# One line per sync on the terminal (stderr), with the time; a 500 leaves its traceback there too.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"verbose": {"format": "[{asctime}] {levelname} {name}: {message}", "style": "{"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "verbose"}},
    "loggers": {
        "garage": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "strava_integration": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
}
# Garage <-> Strava in token mode (garage-030), from the environment only.
GARAGE_STRAVA_USER = os.environ.get("GARAGE_STRAVA_USER", "")
GARAGE_SYNC_TOKEN = os.environ.get("GARAGE_SYNC_TOKEN", "")
STRAVA_WEBHOOK_SUBSCRIPTION_ID = os.environ.get("STRAVA_WEBHOOK_SUBSCRIPTION_ID", "")
if not GARAGE_STRAVA_USER.strip():
    logging.getLogger("garage").warning(
        "GARAGE_STRAVA_USER is empty: Garage shows Strava as not configured and does not sync.")
