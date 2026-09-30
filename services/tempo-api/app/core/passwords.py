"""Password + TOTP primitives. No I/O; everything here is unit-testable.

* Argon2id (argon2-cffi defaults: t=3, m=64 MiB, p=4) with transparent re-hash when parameters change.
* Verification is constant-cost: an unknown account is checked against a dummy hash so timing does not reveal existence.
* Policy: 12-128 chars, not the username / email local part, not a well-known password.
* TOTP (RFC 6238, SHA-1, 30 s, 6 digits) with a +/-1 step window and replay protection via the last accepted step.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, InvalidToken

_ph = PasswordHasher()
_DUMMY = _ph.hash("tempo-dummy-password-for-constant-time")
MIN_LEN, MAX_LEN = 12, 128
_COMMON = {
    "password1234", "123456789012", "qwertyuiop12", "letmein12345", "welcome12345", "administrator", "passwordpassword", "iloveyou1234",
    "changeme1234", "password12345", "1234567890123", "abcdefghijkl", "qwerty123456", "tempo1234567", "ensemble12345", "warehouse1234",
}


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(stored: str | None, pw: str) -> tuple[bool, bool]:
    """Returns (ok, needs_rehash). Always does one Argon2 verification, even with no stored hash."""
    try:
        _ph.verify(stored or _DUMMY, pw)
    except (VerificationError, InvalidHashError):
        return False, False
    if stored is None:
        return False, False
    return True, _ph.check_needs_rehash(stored)


def policy_problems(pw: str, *, username: str | None = None, email: str | None = None) -> list[str]:
    out = []
    if len(pw) < MIN_LEN:
        out.append(f"use at least {MIN_LEN} characters")
    if len(pw) > MAX_LEN:
        out.append(f"use at most {MAX_LEN} characters")
    low = pw.lower()
    for ident in (username, (email or "").split("@")[0]):
        if ident and len(ident) >= 3 and ident.lower() in low:
            out.append("do not include your username or email name")
            break
    if low in _COMMON or len(set(low)) < 5:
        out.append("choose a less predictable password")
    return out


# ---------------- TOTP ----------------
def _fernet(key_material: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("tempo-totp|" + key_material).encode()).digest()))


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def encrypt_secret(secret: str, key_material: str) -> str:
    return _fernet(key_material).encrypt(secret.encode()).decode()


def decrypt_secret(token: str, key_material: str) -> str | None:
    try:
        return _fernet(key_material).decrypt(token.encode()).decode()
    except InvalidToken:
        return None


def _code(secret_b32: str, step: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    return f"{(struct.unpack('>I', mac[off:off + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def totp_now(secret_b32: str, at: float | None = None) -> str:
    return _code(secret_b32, int((at if at is not None else time.time()) // 30))


def verify_totp(secret_b32: str, code: str, last_step: int, at: float | None = None) -> int | None:
    """Returns the accepted time-step (persist it as last_step) or None. A step <= last_step is a replay."""
    code = code.strip().replace(" ", "")
    if len(code) != 6 or not code.isdigit():
        return None
    now = int((at if at is not None else time.time()) // 30)
    for step in (now, now - 1, now + 1):
        if step > last_step and hmac.compare_digest(_code(secret_b32, step), code):
            return step
    return None


def otpauth_uri(secret_b32: str, account: str, issuer: str = "Tempo") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(account)}?secret={secret_b32}&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30"
