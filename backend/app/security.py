"""Password hashing and session tokens.

Uses stdlib `hashlib.scrypt` rather than argon2/bcrypt so the auth path carries
no native build dependency. scrypt at these parameters is a sound choice for a
small cohort; swap in argon2id if this ever grows past a learning build.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# Single source of truth: FastAPI's Cookie(alias=...) needs a literal, so this
# cannot come from settings without the two drifting apart.
SESSION_COOKIE = "advisor_session"

_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_DK_LEN = 32


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_DK_LEN,
        maxmem=2**26,
    )
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N,
        _SCRYPT_R,
        _SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(dk).decode(),
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, dk_b64 = encoded.split("$")
        if scheme != "scrypt":
            return False
        candidate = hashlib.scrypt(
            password.encode("utf-8"),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(base64.b64decode(dk_b64)),
            maxmem=2**26,
        )
        return hmac.compare_digest(candidate, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


def new_session_token() -> tuple[str, str]:
    """Return (plaintext token for the cookie, sha256 hash to store)."""
    token = secrets.token_urlsafe(40)
    return token, hash_session_token(token)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
