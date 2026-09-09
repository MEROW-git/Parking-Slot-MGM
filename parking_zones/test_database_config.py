"""
Unit tests for SomPark database configuration precedence, validation,
SSL certificate isolation, and credential masking.
"""

import os
from unittest.mock import patch
from pathlib import Path
from django.test import SimpleTestCase
from django.core.exceptions import ImproperlyConfigured

from parking_management.settings import database_config, _get_ssl_options, BASE_DIR


class DatabaseConfigTests(SimpleTestCase):
    """
    Tests database_config() behavior across all tiers of configuration:
    Tier 1: Separate DB_* variables (highest precedence)
    Tier 2: DATABASE_URL
    Tier 3: SQLite fallback
    """

    def test_tier1_separate_mysql_variables(self):
        """Separate DB_* variables produce standard Django MySQL settings."""
        env = {
            'DB_CONNECTION': 'mysql',
            'DB_HOST': '127.0.0.1',
            'DB_PORT': '3306',
            'DB_DATABASE': 'my_app_db',
            'DB_USERNAME': 'root',
            'DB_PASSWORD': 'secretpassword',
            'DB_CONN_MAX_AGE': '120',
            'DATABASE_URL': '',
            'MYSQL_SSL_CA': '',
            'MYSQL_SSL_CA_PEM': '',
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = database_config()
            self.assertEqual(cfg['ENGINE'], 'django.db.backends.mysql')
            self.assertEqual(cfg['NAME'], 'my_app_db')
            self.assertEqual(cfg['HOST'], '127.0.0.1')
            self.assertEqual(cfg['PORT'], '3306')
            self.assertEqual(cfg['USER'], 'root')
            self.assertEqual(cfg['PASSWORD'], 'secretpassword')
            self.assertEqual(cfg['CONN_MAX_AGE'], 120)
            self.assertEqual(cfg['OPTIONS']['charset'], 'utf8mb4')
            self.assertNotIn('ssl', cfg['OPTIONS'])

    def test_tier1_takes_precedence_over_database_url(self):
        """When both DB_CONNECTION and DATABASE_URL are set, DB_CONNECTION wins."""
        env = {
            'DB_CONNECTION': 'mysql',
            'DB_HOST': 'local-host-wins',
            'DB_PORT': '3307',
            'DB_DATABASE': 'local_db_wins',
            'DB_USERNAME': 'local_user',
            'DB_PASSWORD': 'local_password',
            'DATABASE_URL': 'mysql+pymysql://remote_user:remote_pass@remote-host:3306/remote_db',
            'MYSQL_SSL_CA': '',
            'MYSQL_SSL_CA_PEM': '',
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = database_config()
            self.assertEqual(cfg['HOST'], 'local-host-wins')
            self.assertEqual(cfg['NAME'], 'local_db_wins')
            self.assertEqual(cfg['USER'], 'local_user')
            self.assertEqual(cfg['PORT'], '3307')
            self.assertEqual(cfg['PASSWORD'], 'local_password')

    def test_tier2_database_url_fallback(self):
        """When DB_CONNECTION is unset, DATABASE_URL is used."""
        env = {
            'DB_CONNECTION': '',
            'DATABASE_URL': 'mysql+pymysql://aiven_admin:aiven_secret@mysql-sompark.aivencloud.com:15234/defaultdb',
            'DB_CONN_MAX_AGE': '90',
            'MYSQL_SSL_CA': '',
            'MYSQL_SSL_CA_PEM': '',
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = database_config()
            self.assertEqual(cfg['ENGINE'], 'django.db.backends.mysql')
            self.assertEqual(cfg['NAME'], 'defaultdb')
            self.assertEqual(cfg['USER'], 'aiven_admin')
            self.assertEqual(cfg['PASSWORD'], 'aiven_secret')
            self.assertEqual(cfg['HOST'], 'mysql-sompark.aivencloud.com')
            self.assertEqual(cfg['PORT'], '15234')
            self.assertEqual(cfg['CONN_MAX_AGE'], 90)

    def test_tier3_sqlite_fallback(self):
        """When neither DB_CONNECTION nor DATABASE_URL is set, falls back to SQLite."""
        env = {
            'DB_CONNECTION': '',
            'DATABASE_URL': '',
            'MYSQL_SSL_CA': '',
            'MYSQL_SSL_CA_PEM': '',
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = database_config()
            self.assertEqual(cfg['ENGINE'], 'django.db.backends.sqlite3')
            self.assertEqual(cfg['NAME'], BASE_DIR / 'db.sqlite3')

    def test_reject_unsupported_db_connection(self):
        """Unsupported DB_CONNECTION values raise ImproperlyConfigured with clear message."""
        env = {
            'DB_CONNECTION': 'postgres',
            'DB_HOST': '127.0.0.1',
            'DB_DATABASE': 'db',
            'DB_USERNAME': 'user',
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ImproperlyConfigured) as cm:
                database_config()
            self.assertIn("Unsupported DB_CONNECTION 'postgres'", str(cm.exception))

    def test_validate_required_mysql_fields(self):
        """Missing host, database, or username raises ImproperlyConfigured listing missing variables."""
        env = {
            'DB_CONNECTION': 'mysql',
            'DB_HOST': '',
            'DB_DATABASE': 'my_app_db',
            'DB_USERNAME': '',
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ImproperlyConfigured) as cm:
                database_config()
            err = str(cm.exception)
            self.assertIn('DB_HOST', err)
            self.assertIn('DB_USERNAME', err)

    def test_validate_port_range_and_type(self):
        """Non-integer or out-of-range ports are rejected with ImproperlyConfigured."""
        # Non-integer port
        with patch.dict(os.environ, {'DB_CONNECTION': 'mysql', 'DB_HOST': '127.0.0.1', 'DB_DATABASE': 'db', 'DB_USERNAME': 'u', 'DB_PORT': 'not_a_port'}, clear=True):
            with self.assertRaises(ImproperlyConfigured) as cm:
                database_config()
            self.assertIn("Invalid DB_PORT 'not_a_port'", str(cm.exception))

        # Port out of range
        with patch.dict(os.environ, {'DB_CONNECTION': 'mysql', 'DB_HOST': '127.0.0.1', 'DB_DATABASE': 'db', 'DB_USERNAME': 'u', 'DB_PORT': '70000'}, clear=True):
            with self.assertRaises(ImproperlyConfigured) as cm:
                database_config()
            self.assertIn("Invalid DB_PORT '70000'", str(cm.exception))

    def test_default_port_applied_when_blank(self):
        """Blank DB_PORT defaults safely to 3306."""
        env = {
            'DB_CONNECTION': 'mysql',
            'DB_HOST': '127.0.0.1',
            'DB_PORT': '',
            'DB_DATABASE': 'my_app_db',
            'DB_USERNAME': 'root',
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = database_config()
            self.assertEqual(cfg['PORT'], '3306')

    def test_password_with_special_characters(self):
        """Passwords containing #, spaces, quotes, and symbols are preserved accurately."""
        special_pw = 'p#ss w0rd!@$%^&*()_+~"\'`'
        env = {
            'DB_CONNECTION': 'mysql',
            'DB_HOST': '127.0.0.1',
            'DB_DATABASE': 'my_app_db',
            'DB_USERNAME': 'root',
            'DB_PASSWORD': special_pw,
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = database_config()
            self.assertEqual(cfg['PASSWORD'], special_pw)

    def test_empty_password_allowed(self):
        """Local MySQL instances with no password are fully supported."""
        env = {
            'DB_CONNECTION': 'mysql',
            'DB_HOST': '127.0.0.1',
            'DB_DATABASE': 'my_app_db',
            'DB_USERNAME': 'root',
            'DB_PASSWORD': '',
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = database_config()
            self.assertEqual(cfg['PASSWORD'], '')

    def test_local_mysql_never_applies_ssl_when_unconfigured(self):
        """
        Local MySQL runs without SSL. Even if certs/aiven-ca.pem exists on disk,
        SSL options are never applied unless MYSQL_SSL_CA or MYSQL_SSL_CA_PEM is set.
        """
        env = {
            'DB_CONNECTION': 'mysql',
            'DB_HOST': '127.0.0.1',
            'DB_DATABASE': 'my_app_db',
            'DB_USERNAME': 'root',
            'MYSQL_SSL_CA': '',
            'MYSQL_SSL_CA_PEM': '',
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertIsNone(_get_ssl_options())
            cfg = database_config()
            self.assertNotIn('ssl', cfg['OPTIONS'])

    def test_ssl_options_applied_when_explicitly_configured(self):
        """When MYSQL_SSL_CA is explicitly specified and points to a file, SSL options are enabled."""
        test_ca = BASE_DIR / 'certs' / 'test-ca.pem'
        test_ca.parent.mkdir(parents=True, exist_ok=True)
        test_ca.write_text('TEST CERTIFICATE CONTENT')

        try:
            env = {
                'DB_CONNECTION': 'mysql',
                'DB_HOST': 'remote-host',
                'DB_DATABASE': 'my_app_db',
                'DB_USERNAME': 'remote_user',
                'MYSQL_SSL_CA': str(test_ca),
            }
            with patch.dict(os.environ, env, clear=True):
                cfg = database_config()
                self.assertIn('ssl', cfg['OPTIONS'])
                self.assertEqual(cfg['OPTIONS']['ssl']['ca'], str(test_ca.resolve()))
        finally:
            if test_ca.exists():
                test_ca.unlink()

    def test_never_print_credentials_in_errors(self):
        """Configuration errors must never leak passwords or sensitive credentials."""
        secret_value = 'TOP_SECRET_PASSWORD_12345'
        env = {
            'DB_CONNECTION': 'mysql',
            'DB_HOST': '',
            'DB_DATABASE': 'my_app_db',
            'DB_USERNAME': 'root',
            'DB_PASSWORD': secret_value,
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(ImproperlyConfigured) as cm:
                database_config()
            self.assertNotIn(secret_value, str(cm.exception))
