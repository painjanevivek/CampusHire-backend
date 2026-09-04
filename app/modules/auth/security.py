import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import struct
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings

password_hasher = PasswordHasher(type=Type.ID)


def normalize_email(email: str) -> str:
    return email.strip().casefold()


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
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _totp_key(secret: str) -> bytes:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    return base64.b32decode(padded, casefold=True)


def totp_code(secret: str, *, at_time: int | None = None) -> str:
    counter = int((at_time if at_time is not None else time.time()) // 30)
    digest = hmac.new(_totp_key(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def verify_totp(secret: str, code: str, *, at_time: int | None = None) -> bool:
    if len(code) != 6 or not code.isdigit():
        return False
    now = at_time if at_time is not None else int(time.time())
    return any(
        secrets.compare_digest(totp_code(secret, at_time=now + offset * 30), code)
        for offset in (-1, 0, 1)
    )


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
