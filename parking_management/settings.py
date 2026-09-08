"""
Django settings for parking_management project.
SomPark - Smart Parking for Phnom Penh Capital
(ចំណតឆ្លាតវៃ សម្រាប់រាជធានីភ្នំពេញ)
"""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    'django-insecure-sompark-khmer-parking-phnom-penh-2026-safe-key'
)

# Robust debug parsing: handles non-boolean env values (e.g. Windows DEBUG=release)
_debug_env = os.environ.get('DEBUG', 'True').strip().lower()
DEBUG = _debug_env in ('true', '1', 't', 'yes')

_allowed_hosts = os.environ.get('ALLOWED_HOSTS', '*')
if _allowed_hosts == '*':
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(',') if h.strip()]

CSRF_TRUSTED_ORIGINS = [
    'https://*.run.app',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'source.apps.SourceConfig',
    'users.apps.UsersConfig',
    'parking_zones.apps.ParkingZonesConfig',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'parking_management.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [
            BASE_DIR / 'templates',
            BASE_DIR / 'source' / 'templates',
            BASE_DIR / 'parking_zones' / 'templates',
            BASE_DIR / 'users' / 'templates',
        ],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'source.context_processors.sompark_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'parking_management.wsgi.application'
ASGI_APPLICATION = 'parking_management.asgi.application'

def database_config():
    """Build the Django database configuration from DATABASE_URL."""
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if not database_url:
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }

    parsed = urlparse(database_url)
    if parsed.scheme.lower() == 'sqlite':
        sqlite_name = unquote(parsed.path.lstrip('/')) or 'db.sqlite3'
        return {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': sqlite_name if sqlite_name == ':memory:' else BASE_DIR / sqlite_name,
        }

    if parsed.scheme.lower() not in {'mysql', 'mysql+pymysql'}:
        raise ImproperlyConfigured(
            'DATABASE_URL must use mysql://, mysql+pymysql://, or sqlite://.'
        )

    database_name = unquote(parsed.path.lstrip('/'))
    if not all((parsed.hostname, parsed.username, database_name)):
        raise ImproperlyConfigured(
            'DATABASE_URL must include a host, username, and database name.'
        )

    options = {'charset': 'utf8mb4'}
    ssl_ca = os.environ.get('MYSQL_SSL_CA', '').strip()
    if ssl_ca:
        ssl_ca_path = Path(ssl_ca).expanduser()
        if not ssl_ca_path.is_absolute():
            ssl_ca_path = BASE_DIR / ssl_ca_path
        options['ssl'] = {'ca': str(ssl_ca_path.resolve())}

    return {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': database_name,
        'USER': unquote(parsed.username),
        'PASSWORD': unquote(parsed.password or ''),
        'HOST': parsed.hostname,
        'PORT': str(parsed.port or 3306),
        'CONN_MAX_AGE': int(os.environ.get('DB_CONN_MAX_AGE', '60')),
        'OPTIONS': options,
    }


DATABASES = {'default': database_config()}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Phnom_Penh'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'public',
    BASE_DIR / 'static',
]

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'login'

X_FRAME_OPTIONS = 'SAMEORIGIN'
