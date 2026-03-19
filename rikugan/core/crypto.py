"""Optional API key encryption using PBKDF2 + AES-256-GCM.

The ``cryptography`` package is a transitive dependency of ``anthropic``,
``openai``, and ``mcp`` (via ``httpx``).  If it is not available in the
host Python environment the feature degrades gracefully — ``is_available()``
returns False and the settings checkbox is disabled.
"""

from __future__ import annotations

import base64
import json
import os

_VERIFY_SENTINEL = "rikugan-encryption-v1"
_PBKDF2_ITERATIONS = 600_000

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    _HAS_CRYPTO = True
except ImportError:
    _HAS_CRYPTO = False


def is_available() -> bool:
    """Return True if the ``cryptography`` library is importable."""
    return _HAS_CRYPTO


def _derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from *password* + *salt*."""
    kdf = PBKDF2HMAC(
        algorithm=SHA256(),
        length=32,
        salt=salt,
        iterations=_PBKDF2_ITERATIONS,
    )
    return kdf.derive(password.encode("utf-8"))


def encrypt_keys(password: str, key_data: dict) -> dict:
    """Encrypt *key_data* and return a dict suitable for JSON serialisation.

    Returns ``{"salt": ..., "nonce": ..., "ciphertext": ...}`` where each
    value is a Base-64 encoded string.
    """
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(password, salt)
    plaintext = json.dumps(
        {"verify": _VERIFY_SENTINEL, "keys": key_data},
    ).encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, plaintext, None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ct).decode(),
    }


def decrypt_keys(password: str, enc_block: dict) -> dict:
    """Decrypt *enc_block* and return the original key-data dict.

    Raises ``ValueError`` on wrong password or corrupted data.
    """
    try:
        salt = base64.b64decode(enc_block["salt"])
        nonce = base64.b64decode(enc_block["nonce"])
        ct = base64.b64decode(enc_block["ciphertext"])
    except (KeyError, Exception) as exc:
        raise ValueError("Malformed encryption block") from exc

    key = _derive_key(password, salt)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ct, None)
    except InvalidTag as exc:
        raise ValueError("Wrong password or corrupted data") from exc

    payload = json.loads(plaintext)
    if payload.get("verify") != _VERIFY_SENTINEL:
        raise ValueError("Decryption verification failed")
    return payload["keys"]
