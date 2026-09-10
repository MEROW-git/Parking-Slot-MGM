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
load_dotenv(BASE_DIR / '.env', override=True)

SECRET_KEY = os.environ.get('SECRET_KEY', '').strip()
if not SECRET_KEY:
    raise ImproperlyConfigured(
        'Set SECRET_KEY in .env or the deployment environment before starting Django. '
        'See .env.example for instructions.'
    )

# Reserved for future integrations; these do not enable a provider by themselves.
# Keep private provider keys on the server, out of template contexts and responses.
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '').strip()

# Gemini AI Feature Flag: parse gemini_ai, GEMINI_AI, or GEMINI_AI_ENABLED from .env / environment
_gemini_ai_raw = (
    os.environ.get('gemini_ai') or
    os.environ.get('GEMINI_AI') or
    os.environ.get('GEMINI_AI_ENABLED')
)
if _gemini_ai_raw is not None:
    _gemini_ai_clean = str(_gemini_ai_raw).strip().lower()
    GEMINI_AI_ENABLED = _gemini_ai_clean in ('true', '1', 't', 'yes', 'on')
else:
    GEMINI_AI_ENABLED = True

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
    'django.contrib.humanize',
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


def _get_ssl_options():
    """
    Resolve SSL options for remote MySQL connections (e.g. Aiven).
    Only applies certificate settings when explicitly configured via
    MYSQL_SSL_CA or MYSQL_SSL_CA_PEM environment variables.
    Never auto-enables SSL for local MySQL installations.
    """
    ssl_ca = os.environ.get('MYSQL_SSL_CA', '').strip()
    ssl_ca_pem = os.environ.get('MYSQL_SSL_CA_PEM', '').strip()

    if not ssl_ca and not ssl_ca_pem:
        return None

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
        return {'ca': str(ca_file_path.resolve())}
    elif ssl_ca:
        ssl_ca_path = Path(ssl_ca).expanduser()
        if not ssl_ca_path.is_absolute():
            ssl_ca_path = BASE_DIR / ssl_ca_path
        if ssl_ca_path.exists():
            return {'ca': str(ssl_ca_path.resolve())}
        else:
            raise ImproperlyConfigured(
                f"Configured MYSQL_SSL_CA file not found: {ssl_ca}"
            )
    return None


def database_config():
    """
    Build the Django database configuration with explicit precedence:
    1. Separate DB_* configuration (if DB_CONNECTION is provided)
    2. DATABASE_URL (e.g. Aiven MySQL deployment or SQLite URL)
    3. SQLite fallback (db.sqlite3)
    """
    conn_max_age_raw = os.environ.get('DB_CONN_MAX_AGE', '60').strip()
    try:
        conn_max_age = int(conn_max_age_raw)
    except ValueError:
        conn_max_age = 60

    # 1. Tier 1: Separate DB_* variables take highest precedence
    db_connection = os.environ.get('DB_CONNECTION', '').strip().lower()
    if db_connection:
        if db_connection not in {'mysql', 'mysql+pymysql', 'sqlite'}:
            raise ImproperlyConfigured(
                f"Unsupported DB_CONNECTION '{db_connection}'. Supported connections: mysql, sqlite."
            )

        if db_connection == 'sqlite':
            sqlite_name = os.environ.get('DB_DATABASE', '').strip() or 'db.sqlite3'
            return {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': sqlite_name if sqlite_name == ':memory:' else BASE_DIR / sqlite_name,
            }

        # MySQL configuration via separate variables
        db_host = os.environ.get('DB_HOST', '').strip()
        db_port_raw = os.environ.get('DB_PORT', '3306').strip()
        if not db_port_raw:
            db_port_raw = '3306'
        db_database = os.environ.get('DB_DATABASE', '').strip()
        db_username = os.environ.get('DB_USERNAME', '').strip()
        db_password = os.environ.get('DB_PASSWORD', '')

        if not db_host or not db_database or not db_username:
            missing = []
            if not db_host:
                missing.append('DB_HOST')
            if not db_database:
                missing.append('DB_DATABASE')
            if not db_username:
                missing.append('DB_USERNAME')
            raise ImproperlyConfigured(
                f"When DB_CONNECTION=mysql is set, required variables are missing: {', '.join(missing)}."
            )

        try:
            db_port = int(db_port_raw)
            if not (1 <= db_port <= 65535):
                raise ValueError()
        except (ValueError, TypeError):
            raise ImproperlyConfigured(
                f"Invalid DB_PORT '{db_port_raw}'. Must be an integer between 1 and 65535."
            )

        options = {'charset': 'utf8mb4'}
        ssl_opts = _get_ssl_options()
        if ssl_opts:
            options['ssl'] = ssl_opts

        return {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': db_database,
            'USER': db_username,
            'PASSWORD': db_password,
            'HOST': db_host,
            'PORT': str(db_port),
            'CONN_MAX_AGE': conn_max_age,
            'OPTIONS': options,
        }

    # 2. Tier 2: DATABASE_URL configuration
    database_url = os.environ.get('DATABASE_URL', '').strip()
    if database_url:
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

        port = parsed.port or 3306
        if not (1 <= port <= 65535):
            raise ImproperlyConfigured(
                f"Invalid port '{port}' in DATABASE_URL. Must be an integer between 1 and 65535."
            )

        options = {'charset': 'utf8mb4'}
        ssl_opts = _get_ssl_options()
        if ssl_opts:
            options['ssl'] = ssl_opts

        return {
            'ENGINE': 'django.db.backends.mysql',
            'NAME': database_name,
            'USER': unquote(parsed.username),
            'PASSWORD': unquote(parsed.password or ''),
            'HOST': parsed.hostname,
            'PORT': str(port),
            'CONN_MAX_AGE': conn_max_age,
            'OPTIONS': options,
        }

    # 3. Tier 3: SQLite fallback
    return {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
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
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'

X_FRAME_OPTIONS = 'ALLOWALL'

# SomPark Workflow & Payment Configuration
# In production, set DEMO_PAYMENT_ENABLED=False to require verified external bank gateways
DEMO_PAYMENT_ENABLED = os.environ.get('DEMO_PAYMENT_ENABLED', 'True').strip().lower() in ('true', '1', 'yes')
PAYMENT_TIMEOUT_MINUTES = int(os.environ.get('PAYMENT_TIMEOUT_MINUTES', '15'))
ARRIVAL_HOLD_HOURS = int(os.environ.get('ARRIVAL_HOLD_HOURS', '3'))
DEPOSIT_ARRIVAL_HOLD_HOURS = int(os.environ.get('DEPOSIT_ARRIVAL_HOLD_HOURS', '5'))
EXIT_WINDOW_MINUTES = int(os.environ.get('EXIT_WINDOW_MINUTES', '5'))
DEFAULT_OVERSTAY_MULTIPLIER = float(os.environ.get('DEFAULT_OVERSTAY_MULTIPLIER', '2.0'))

# Anti-Spam & Hold Policy Configuration
MAX_ACTIVE_RESERVATIONS_PER_USER = int(os.environ.get('MAX_ACTIVE_RESERVATIONS_PER_USER', '1'))
MAX_PAY_LATER_HOLDS_PER_24H = int(os.environ.get('MAX_PAY_LATER_HOLDS_PER_24H', '3'))
UNPAID_CANCEL_COOLDOWN_MINUTES = int(os.environ.get('UNPAID_CANCEL_COOLDOWN_MINUTES', '10'))
UNPAID_NOSHOW_THRESHOLD = int(os.environ.get('UNPAID_NOSHOW_THRESHOLD', '2'))
UNPAID_NOSHOW_PENALTY_HOURS = int(os.environ.get('UNPAID_NOSHOW_PENALTY_HOURS', '24'))
BOOKING_RATE_LIMIT_PER_MINUTE = int(os.environ.get('BOOKING_RATE_LIMIT_PER_MINUTE', '10'))
BOOKING_IP_RATE_LIMIT_PER_MINUTE = int(os.environ.get('BOOKING_IP_RATE_LIMIT_PER_MINUTE', '30'))

# Asset versioning for cache busting
ASSET_VERSION = os.environ.get('ASSET_VERSION', '1.5.0')
