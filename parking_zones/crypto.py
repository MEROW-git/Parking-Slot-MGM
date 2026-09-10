"""
Application-level authenticated encryption and keyed HMAC index for vehicle license plates.

Key Separation:
- PLATE_ENCRYPTION_KEY: Dedicated 32-byte URL-safe base64 Fernet key for AES-128-CBC + HMAC-SHA256
  authenticated encryption with randomized IV and timestamp. Supports comma-separated keys for zero-downtime rotation.
- PLATE_SEARCH_HMAC_KEY: Dedicated 32-byte secret key for keyed HMAC-SHA256 exact matching and lookup indexes.
- SECRET_KEY is never used for plate encryption or HMAC computation.

Invariants:
- Missing or wrong keys fail explicitly with actionable configuration/decryption errors.
- Ciphertext is prefixed with 'enc:v1:' to enable deterministic discrimination from unencrypted legacy plates.
- Unencrypted legacy records are transparently returned as plaintext during staged migration.
"""
import hashlib
import hmac
import os
import re
import secrets
from django.conf import settings
from cryptography.fernet import Fernet, MultiFernet, InvalidToken


CIPHERTEXT_PREFIX = 'enc:v1:'


class PlateCryptoConfigurationError(Exception):
    """Raised when encryption or HMAC keys are missing, improperly formatted, or invalid."""
    pass


class PlateDecryptionError(Exception):
    """Raised when ciphertext authentication or decryption fails."""
    pass


def normalize_plate_for_hmac(plate: str) -> str:
    """
    Standard normalization for license plates before HMAC computation:
    strips whitespace, hyphens, periods, underscores, and converts to uppercase.
    Example: 'Phnom Penh 2AZ-1234' -> 'PHNOMPENH2AZ1234'
    """
    if not plate:
        return ''
    return re.sub(r'[\s\-_.]+', '', str(plate)).upper()


def generate_fernet_key() -> str:
    """Generates a new secure 32-byte URL-safe base64-encoded Fernet key."""
    return Fernet.generate_key().decode('ascii')


def generate_hmac_key() -> str:
    """Generates a new secure 256-bit (32-byte) hex-encoded HMAC key."""
    return secrets.token_hex(32)


def get_encryption_keys() -> list[bytes]:
    """
    Retrieves and validates plate encryption keys from environment or Django settings.
    Supports comma-separated keys for rotation: primary key first, followed by previous keys.
    """
    raw = os.environ.get('PLATE_ENCRYPTION_KEY') or getattr(settings, 'PLATE_ENCRYPTION_KEY', '')
    if not raw or not str(raw).strip():
        # Check if running within automated test runner where settings provides test keys
        test_key = getattr(settings, 'TEST_PLATE_ENCRYPTION_KEY', '')
        if test_key:
            raw = test_key
        else:
            raise PlateCryptoConfigurationError(
                "Missing required environment variable 'PLATE_ENCRYPTION_KEY'. "
                "Generate a key using: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\" "
                "and set it in your environment."
            )

    key_tokens = [k.strip() for k in str(raw).split(',') if k.strip()]
    if not key_tokens:
        raise PlateCryptoConfigurationError("PLATE_ENCRYPTION_KEY contains no valid key tokens.")

    validated_keys = []
    for idx, token in enumerate(key_tokens):
        try:
            key_bytes = token.encode('ascii')
            # Test key validity with Fernet constructor
            Fernet(key_bytes)
            validated_keys.append(key_bytes)
        except Exception as e:
            raise PlateCryptoConfigurationError(
                f"PLATE_ENCRYPTION_KEY token #{idx+1} is invalid: {e}. "
                "Must be a 32-byte URL-safe base64-encoded key."
            )
    return validated_keys


def get_search_hmac_key() -> bytes:
    """
    Retrieves and validates the separate keyed HMAC key for plate lookup indexes.
    """
    raw = os.environ.get('PLATE_SEARCH_HMAC_KEY') or getattr(settings, 'PLATE_SEARCH_HMAC_KEY', '')
    if not raw or not str(raw).strip():
        test_hmac_key = getattr(settings, 'TEST_PLATE_SEARCH_HMAC_KEY', '')
        if test_hmac_key:
            raw = test_hmac_key
        else:
            raise PlateCryptoConfigurationError(
                "Missing required environment variable 'PLATE_SEARCH_HMAC_KEY'. "
                "Generate a key using: python -c \"import secrets; print(secrets.token_hex(32))\" "
                "and set it in your environment."
            )

    key_str = str(raw).strip()
    if len(key_str) < 16:
        raise PlateCryptoConfigurationError(
            "PLATE_SEARCH_HMAC_KEY must be at least 16 characters (recommended 64-character hex string)."
        )
    return key_str.encode('utf-8')


def get_plate_cipher() -> MultiFernet:
    """Returns a MultiFernet instance constructed from configured keys."""
    keys = get_encryption_keys()
    fernets = [Fernet(k) for k in keys]
    return MultiFernet(fernets)


def encrypt_plate(plate: str) -> str:
    """
    Encrypts a plaintext license plate into an authenticated ciphertext prefixed with 'enc:v1:'.
    Empty string is returned as-is. Already-encrypted strings are returned unmodified.
    """
    if not plate:
        return ''
    if str(plate).startswith(CIPHERTEXT_PREFIX):
        return str(plate)

    cipher = get_plate_cipher()
    raw_token = cipher.encrypt(str(plate).encode('utf-8'))
    return f"{CIPHERTEXT_PREFIX}{raw_token.decode('ascii')}"


def decrypt_plate(stored_value: str) -> str:
    """
    Decrypts an authenticated ciphertext plate.
    If the value does not have the 'enc:v1:' prefix, it is treated as legacy unencrypted
    plaintext and returned as-is (preserving backwards compatibility before staged backfill).
    """
    if not stored_value:
        return ''
    val_str = str(stored_value)
    if not val_str.startswith(CIPHERTEXT_PREFIX):
        # Legacy unencrypted plaintext
        return val_str

    token = val_str[len(CIPHERTEXT_PREFIX):]
    cipher = get_plate_cipher()
    try:
        decrypted_bytes = cipher.decrypt(token.encode('ascii'))
        return decrypted_bytes.decode('utf-8')
    except InvalidToken as e:
        raise PlateDecryptionError(
            "Failed to decrypt vehicle license plate. The ciphertext is invalid, corrupted, "
            "or the encryption key does not match the key used to encrypt this record."
        ) from e
    except Exception as e:
        raise PlateDecryptionError(f"Unexpected error during plate decryption: {e}") from e


def compute_plate_hmac(plate: str) -> str:
    """
    Computes a keyed HMAC-SHA256 lookup digest for exact plate matching.
    Normalizes the plate first (stripping hyphens, spaces, lowercases).
    Returns a 64-character lowercase hexadecimal digest.
    Returns '' for empty plates.
    """
    if not plate:
        return ''
    normalized = normalize_plate_for_hmac(plate)
    if not normalized:
        return ''

    hmac_key = get_search_hmac_key()
    return hmac.new(hmac_key, normalized.encode('utf-8'), hashlib.sha256).hexdigest()
