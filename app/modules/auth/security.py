import asyncio
import base64
import hashlib
import json
import secrets
import time
from datetime import UTC, datetime

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

password_hasher = PasswordHasher(type=Type.ID)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def normalize_username(username: str) -> str:
    return username.strip().casefold()


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    """Run memory-hard password hashing without blocking the API event loop."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password_hash: str, password: str) -> bool:
    """Run memory-hard password verification without blocking other requests."""
    return await asyncio.to_thread(verify_password, password_hash, password)


def new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_code(secret: str, *, at_time: int | None = None) -> str:
    instant = datetime.fromtimestamp(at_time if at_time is not None else time.time(), UTC)
    return pyotp.TOTP(secret, digits=6, interval=30).at(instant)


def verify_totp(secret: str, code: str, *, at_time: int | None = None) -> bool:
    if len(code) != 6 or not code.isdigit():
        return False
    instant = datetime.fromtimestamp(at_time if at_time is not None else time.time(), UTC)
    return pyotp.TOTP(secret, digits=6, interval=30).verify(code, for_time=instant, valid_window=1)


def _encryption_key() -> bytes:
    return hashlib.sha256(get_settings().mfa_encryption_key.encode("utf-8")).digest()


def encrypt_totp_secret(secret: str) -> str:
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_encryption_key()).encrypt(nonce, secret.encode("ascii"), b"campushire-mfa")
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_totp_secret(value: str) -> str:
    payload = base64.urlsafe_b64decode(value.encode("ascii"))
    plaintext = AESGCM(_encryption_key()).decrypt(payload[:12], payload[12:], b"campushire-mfa")
    return plaintext.decode("ascii")


def encrypt_sensitive_payload(payload: dict[str, object], purpose: str) -> str:
    nonce = secrets.token_bytes(12)
    plaintext = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_encryption_key()).encrypt(nonce, plaintext, purpose.encode("ascii"))
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")


def decrypt_sensitive_payload(value: str, purpose: str) -> dict[str, object]:
    payload = base64.urlsafe_b64decode(value.encode("ascii"))
    plaintext = AESGCM(_encryption_key()).decrypt(
        payload[:12], payload[12:], purpose.encode("ascii")
    )
    decoded = json.loads(plaintext)
    if not isinstance(decoded, dict):
        raise ValueError("sensitive_payload_invalid")
    return decoded
