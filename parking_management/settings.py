"""
Django settings for parking_management project.
SomPark - Smart Parking for Phnom Penh Capital
(ចំណតឆ្លាតវៃ សម្រាប់រាជធានីភ្នំពេញ)
"""

import os
import re
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

# Robust debug parsing: defaults to False for safe production deployment
_debug_env = os.environ.get('DEBUG', 'False').strip().lower()
DEBUG = _debug_env in ('true', '1', 't', 'yes')

_allowed_hosts = os.environ.get('ALLOWED_HOSTS', '*').strip()
if not _allowed_hosts or _allowed_hosts == '*':
    ALLOWED_HOSTS = ['*']
else:
    ALLOWED_HOSTS = [h.strip() for h in _allowed_hosts.split(',') if h.strip()]
    for host_entry in ('localhost', '127.0.0.1', '0.0.0.0', 'testserver', '.run.app', '.aistudio.google.com'):
        if host_entry not in ALLOWED_HOSTS:
            ALLOWED_HOSTS.append(host_entry)

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
USE_X_FORWARDED_HOST = True

CSRF_TRUSTED_ORIGINS = [
    'https://*.run.app',
    'https://*.aistudio.google.com',
    'https://ai.studio',
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://localhost:8080',
    'http://127.0.0.1:8080',
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
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
    ssl_ca_pem = os.environ.get('MYSQL_SSL_CA_PEM', '').strip()

    def _normalize_pem(pem_str: str) -> str:
        if not pem_str:
            return ''
        pem_str = pem_str.replace('\\n', '\n')
        m = re.search(r'-----BEGIN CERTIFICATE-----(.+?)-----END CERTIFICATE-----', pem_str, re.DOTALL)
        if m:
            b64 = ''.join(m.group(1).split())
            chunks = [b64[i:i+64] for i in range(0, len(b64), 64)]
            return '-----BEGIN CERTIFICATE-----\n' + '\n'.join(chunks) + '\n-----END CERTIFICATE-----\n'
        return pem_str

    # Safely accept the PEM certificate from an environment variable
    raw_pem = None
    if 'BEGIN CERTIFICATE' in ssl_ca:
        raw_pem = _normalize_pem(ssl_ca)
    elif ssl_ca_pem and 'BEGIN CERTIFICATE' in ssl_ca_pem:
        raw_pem = _normalize_pem(ssl_ca_pem)

    ca_file_path = BASE_DIR / 'certs' / 'aiven-ca.pem'
    ca_file_path.parent.mkdir(parents=True, exist_ok=True)

    if raw_pem:
        if not ca_file_path.exists() or ca_file_path.read_text().strip() != raw_pem.strip():
            ca_file_path.write_text(raw_pem.strip() + '\n')
        options['ssl'] = {'ca': str(ca_file_path.resolve())}
    elif ssl_ca:
        ssl_ca_path = Path(ssl_ca).expanduser()
        if not ssl_ca_path.is_absolute():
            ssl_ca_path = BASE_DIR / ssl_ca_path
        if ssl_ca_path.exists():
            options['ssl'] = {'ca': str(ssl_ca_path.resolve())}
        elif ca_file_path.exists():
            options['ssl'] = {'ca': str(ca_file_path.resolve())}
    elif ca_file_path.exists():
        options['ssl'] = {'ca': str(ca_file_path.resolve())}

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

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'home'
LOGOUT_REDIRECT_URL = 'login'

X_FRAME_OPTIONS = 'ALLOWALL'

