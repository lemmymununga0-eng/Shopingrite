"""Verifies Supabase access tokens. Identity and role come ONLY from the verified token."""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings

bearer = HTTPBearer(auto_error=False)
REVIEWER_ROLES = {"analyst", "admin"}
VALID_ROLES = {"customer", "analyst", "admin"}

_jwks_clients: dict = {}


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    role: str
    token: str

    @property
    def can_review(self) -> bool:
        return self.role in REVIEWER_ROLES


def _unauthorized(detail="Invalid or missing authentication token"):
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def decode_token(token: str, s: Settings) -> dict:
    """Return verified claims or raise jwt.PyJWTError.

    The key type is chosen from the token's declared algorithm, but each branch only ACCEPTS its own
    algorithms, so a token cannot pick a weaker method: HS256 needs the shared secret, ES256/RS256
    need a key from the project's JWKS endpoint, and "none" is always rejected.
    """
    alg = jwt.get_unverified_header(token).get("alg")
    opts = {"require": ["exp", "sub"]}
    if alg == "HS256" and s.supabase_jwt_secret:
        return jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"], audience=s.jwt_audience, options=opts)
    if alg in ("ES256", "RS256") and s.supabase_url:
        url = s.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        client = _jwks_clients.setdefault(url, jwt.PyJWKClient(url, cache_keys=True))
        key = client.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256", "RS256"], audience=s.jwt_audience, options=opts)
    raise jwt.PyJWTError("Token algorithm not accepted or authentication not configured")


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    s: Settings = request.app.state.settings
    if creds is None or not creds.credentials:
        raise _unauthorized()
    try:
        claims = decode_token(creds.credentials, s)
    except jwt.PyJWTError:
        raise _unauthorized()
    role = (claims.get("app_metadata") or {}).get("role", "customer")   # app_metadata is not user-editable
    if role not in VALID_ROLES:
        role = "customer"
    return User(id=claims["sub"], email=claims.get("email"), role=role, token=creds.credentials)


def require_reviewer(user: User = Depends(current_user)) -> User:
    if not user.can_review:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only analysts and admins can review alerts")
    return user
