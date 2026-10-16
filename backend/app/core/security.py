"""Security helpers: redaction, password hashing, local demo tokens, correlation ids."""
import base64
import hashlib
import hmac
import os
import re
import secrets
import time
import uuid
from pathlib import Path

import jwt

LOCAL_ISSUER = "fraudguard-local-demo"

_SENSITIVE_KEYS = re.compile(r"(authorization|password|passwd|secret|token|api[-_]?key|apikey|cookie|cvv|cvc|card)",
                             re.IGNORECASE)
_CARD_LIKE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT_LIKE = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
_KEY_PARAM = re.compile(r"(?i)([?&](?:key|api_key|apikey|token|access_token)=)[^&\s]+")
REDACTED = "[REDACTED]"


def redact_text(text: str, limit: int = 500) -> str:
    text = _BEARER.sub(REDACTED, str(text))
    text = _JWT_LIKE.sub(REDACTED, text)
    text = _KEY_PARAM.sub(r"\1" + REDACTED, text)
    text = _CARD_LIKE.sub(REDACTED, text)
    return text[:limit]


def redact(value, depth: int = 0):
    """Return a copy of `value` that is safe to store or log (secrets, tokens and card-like numbers removed)."""
    if depth > 6:
        return REDACTED
    if isinstance(value, dict):
        return {str(k): (REDACTED if _SENSITIVE_KEYS.search(str(k)) else redact(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, str):
        return redact_text(value)
    return value


# ---- password hashing (scrypt; standard library only) ----
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# Used to keep login timing similar when the account does not exist.
DUMMY_HASH = hash_password(secrets.token_urlsafe(12))


# ---- local demonstration tokens ----
def resolve_local_secret(configured: str, data_dir: Path) -> str:
    """Use the configured secret, or create a random per-machine one (git-ignored file)."""
    if configured:
        if len(configured) < 32:
            raise RuntimeError("LOCAL_AUTH_SECRET must be at least 32 characters.")
        return configured
    path = data_dir / "local_auth_secret.txt"
    data_dir.mkdir(parents=True, exist_ok=True)
    if path.exists():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 32:
            return value
    value = secrets.token_urlsafe(48)
    path.write_text(value, encoding="utf-8")
    return value


def issue_local_token(user_id: str, email: str, role: str, secret: str, audience: str, minutes: int) -> str:
    now = int(time.time())
    claims = {"sub": user_id, "email": email, "aud": audience, "iss": LOCAL_ISSUER, "iat": now,
              "exp": now + minutes * 60, "app_metadata": {"role": role}}
    return jwt.encode(claims, secret, algorithm="HS256")


# ---- correlation ids and client identity ----
_CID_OK = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def correlation_id(incoming: str | None) -> str:
    return incoming if incoming and _CID_OK.match(incoming) else uuid.uuid4().hex


def client_hash(host: str | None) -> str:
    """A short, non-reversible tag for a client address (so events can be grouped without storing IPs)."""
    return hashlib.sha256(("fg-salt|" + (host or "unknown")).encode()).hexdigest()[:16]
