"""Symmetric encryption for secrets-at-rest (broker access tokens, etc.).

Uses Fernet (AES-128-CBC + HMAC) derived from SECRET_KEY. This is deliberately
simple: single-user, single-machine deployment, no KMS integration needed yet.
If this platform ever moves to multi-user or cloud deployment, swap this
module for a real secrets manager — nothing else in the codebase should need
to change since callers only see encrypt_secret/decrypt_secret.
"""

import base64
import hashlib

from cryptography.fernet import Fernet

from app.config import get_settings


def _fernet() -> Fernet:
    settings = get_settings()
    # Derive a 32-byte key deterministically from SECRET_KEY so we don't need
    # a second secret to manage.
    digest = hashlib.sha256(settings.secret_key.encode("utf-8")).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
