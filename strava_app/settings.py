import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get('SECRET_KEY', 'django-insecure-local-dev-only')

DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', 'localhost 127.0.0.1').split()

CSRF_TRUSTED_ORIGINS = [
    f"https://{host}" for host in ALLOWED_HOSTS if host not in ('localhost', '127.0.0.1')
] + ['http://localhost:8000', 'http://127.0.0.1:8000']


# Application definition

INSTALLED_APPS = [
    'unfold',  # modern admin theme — MUST precede django.contrib.admin
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'axes',
    'strava_integration',
]

# django-unfold admin theme. Minimal config; see https://unfoldadmin.com/docs/
UNFOLD = {
    "SITE_TITLE": "Stravagancia Admin",
    "SITE_HEADER": "Stravagancia",
}

# django-axes: brute-force protection on the login form.
# AxesStandaloneBackend must come first so failed attempts are counted before
# the normal credential check.
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    # Must be last: wraps the login view to record/raise on failed attempts.
    'axes.middleware.AxesMiddleware',
]

# django-axes configuration
AXES_FAILURE_LIMIT = 5                              # failed attempts before lockout
AXES_COOLOFF_TIME = 1                               # lockout duration, in hours
AXES_RESET_ON_SUCCESS = True                        # a good login clears the counter
# Lock the (IP, username) pair together: stops brute force from one source
# without letting an attacker lock the real user out from every IP.
AXES_LOCKOUT_PARAMETERS = [['ip_address', 'username']]
# Behind Render's proxy, the real client IP is in X-Forwarded-For, not REMOTE_ADDR.
AXES_IPWARE_PROXY_COUNT = 1
AXES_IPWARE_META_PRECEDENCE_ORDER = ['HTTP_X_FORWARDED_FOR', 'REMOTE_ADDR']

ROOT_URLCONF = 'strava_app.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'strava_app.wsgi.application'


# Database — supports both DATABASE_URL (Render/Neon) and individual DB_* vars (local)
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
_db_url = os.environ.get('DATABASE_URL')
if _db_url:
    DATABASES = {'default': dj_database_url.parse(_db_url, conn_max_age=600)}
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': os.getenv('DB_NAME', 'stravagancia'),
            'USER': os.getenv('DB_USER', 'strava'),
            'PASSWORD': os.getenv('DB_PASSWORD', 'strava'),
            'HOST': os.getenv('DB_HOST', 'localhost'),
            'PORT': os.getenv('DB_PORT', '5432'),
        }
    }


# Password validation
# https://docs.djangoproject.com/en/5.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/5.2/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/5.2/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# Default primary key field type
# https://docs.djangoproject.com/en/5.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# Logging — INFO from our app to stdout so it shows up in Render logs.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "[{asctime}] {levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "strava_integration": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

# Public URL of the Grafana instance whose dashboards are embedded in /charts/.
# Local dev defaults to the docker-compose Grafana; in prod set GRAFANA_URL to the
# Render Grafana service URL (the iframe loads in the user's browser, so it must be
# a publicly reachable host, not localhost).
GRAFANA_URL = os.getenv('GRAFANA_URL', 'http://localhost:3001')
