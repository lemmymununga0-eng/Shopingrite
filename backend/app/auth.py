"""Verifies access tokens. Identity and role come ONLY from the verified token, never from the request body."""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings
from .core import permissions as perm
from .core.security import LOCAL_ISSUER, client_hash

bearer = HTTPBearer(auto_error=False)
# Kept for older imports/tests; the real rules live in core/permissions.py.
VALID_ROLES = set(perm.ROLES)

_jwks_clients: dict = {}


@dataclass(frozen=True)
class User:
    id: str
    email: str | None
    role: str
    token: str

    def __post_init__(self):
        object.__setattr__(self, "role", perm.normalize_role(self.role))   # "analyst" -> "fraud_analyst"

    @property
    def is_staff(self) -> bool:
        return self.role in perm.STAFF_ROLES

    @property
    def can_view_all(self) -> bool:
        """May see every fraud prediction (not just their own)."""
        return perm.allowed(self.role, "fraud.view")

    @property
    def can_review(self) -> bool:
        """May review fraud alerts."""
        return perm.allowed(self.role, "fraud.review")

    def has(self, permission: str) -> bool:
        return perm.allowed(self.role, permission)


def _unauthorized(detail="Invalid or missing authentication token"):
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"})


def decode_token(token: str, s: Settings) -> dict:
    """Return verified claims or raise jwt.PyJWTError.

    The key type is chosen from the token's declared algorithm, but each branch only ACCEPTS its own
    algorithms, so a token cannot pick a weaker method: HS256 needs a shared secret, ES256/RS256
    need a key from the project's JWKS endpoint, and "none" is always rejected. Local demonstration tokens
    are accepted only while LOCAL_AUTH_ENABLED is on, and only when signed with the local secret.
    """
    alg = jwt.get_unverified_header(token).get("alg")
    opts = {"require": ["exp", "sub"]}
    if alg == "HS256" and s.local_auth_enabled and s.local_auth_secret:
        unverified = jwt.decode(token, options={"verify_signature": False})
        if unverified.get("iss") == LOCAL_ISSUER:
            return jwt.decode(token, s.local_auth_secret, algorithms=["HS256"], audience=s.jwt_audience,
                              issuer=LOCAL_ISSUER, options=opts)
    if alg == "HS256" and s.supabase_jwt_secret:
        return jwt.decode(token, s.supabase_jwt_secret, algorithms=["HS256"], audience=s.jwt_audience, options=opts)
    if alg in ("ES256", "RS256") and s.supabase_url:
        url = s.supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json"
        client = _jwks_clients.setdefault(url, jwt.PyJWKClient(url, cache_keys=True))
        key = client.get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["ES256", "RS256"], audience=s.jwt_audience, options=opts)
    raise jwt.PyJWTError("Token algorithm not accepted or authentication not configured")


def _note_failure(request: Request, event_type: str, message: str):
    """Hand the reason to the middleware, which records one security event with the correlation id."""
    request.state.security_event = ("medium", "authentication", event_type, message)


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User:
    s: Settings = request.app.state.settings
    if creds is None or not creds.credentials:
        _note_failure(request, "auth.missing_token", "Request without an access token")
        raise _unauthorized()
    try:
        claims = decode_token(creds.credentials, s)
    except jwt.ExpiredSignatureError:
        _note_failure(request, "auth.token_expired", "Expired access token presented")
        raise _unauthorized()
    except jwt.PyJWTError:
        _note_failure(request, "auth.invalid_token", "Invalid access token presented")
        raise _unauthorized()
    except Exception:       # e.g. malformed header; never leak details to the caller
        _note_failure(request, "auth.invalid_token", "Unreadable access token presented")
        raise _unauthorized()
    role = perm.normalize_role((claims.get("app_metadata") or {}).get("role", perm.CUSTOMER))   # app_metadata is not user-editable
    user = User(id=str(claims["sub"]), email=claims.get("email"), role=role, token=creds.credentials)
    request.state.user_id, request.state.user_role = user.id, user.role
    return user


def require(permission: str):
    """Dependency factory: the caller must be signed in AND hold `permission` (checked on the server)."""
    def checker(request: Request, user: User = Depends(current_user)) -> User:
        if not user.has(permission):
            request.state.security_event = ("medium", "authorization", "authz.denied",
                                            f"Role '{user.role}' denied permission '{permission}'")
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to do this")
        return user
    return checker


def require_reviewer(request: Request, user: User = Depends(current_user)) -> User:
    return require("fraud.review")(request, user)


def optional_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> User | None:
    """For public routes that behave differently when signed in. A bad token is still rejected."""
    if creds is None or not creds.credentials:
        return None
    return current_user(request, creds)


def client_tag(request: Request) -> str:
    return client_hash(request.client.host if request.client else None)
