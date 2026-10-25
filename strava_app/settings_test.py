"""Independent settings: never import production settings or load .env."""
import os
from pathlib import Path
from test_support.isolation import database_config, install

install()
BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "synthetic-test-secret-key-never-for-deployment"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
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
DATABASES = {"default": database_config()}
AUTH_PASSWORD_VALIDATORS = []
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
GRAFANA_URL = "http://localhost:3001"
TEST_RUNNER = "django.test.runner.DiscoverRunner"
# Daily sync disabled (its endpoint answers 404); tests that need it use override_settings.
GARAGE_SYNC_TOKEN = ""
# Only the demo receives it, through its helper; under pytest install() drops it from the environment.
GARAGE_STRAVA_USER = os.getenv("GARAGE_STRAVA_USER", "")
