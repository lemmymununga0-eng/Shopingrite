"""Local DEMONSTRATION sign-in and the "who am I" endpoint.

`/auth/local/login` exists only while LOCAL_AUTH_ENABLED=true. It is a convenience for running the project
offline. Production identity is Supabase Auth; never enable local sign-in on a server others can reach.
"""
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..auth import User, client_tag, current_user
from ..core import permissions as perm
from ..core.security import DUMMY_HASH, hash_password, issue_local_token, verify_password
from ..db.models import AppUser
from ..dependencies import correlation

log = logging.getLogger("fraudguard")
router = APIRouter(tags=["auth"])


class LocalLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


class LocalRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=200)
    full_name: str = Field(min_length=2, max_length=120)

    @field_validator("email")
    @classmethod
    def _email_ok(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL.match(v):
            raise ValueError("enter a valid email address")
        return v

    @field_validator("password")
    @classmethod
    def _password_ok(cls, v: str) -> str:
        if not (re.search(r"[A-Za-z]", v) and re.search(r"\d", v)):
            raise ValueError("the password needs at least one letter and one number")
        return v

    @field_validator("full_name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        return " ".join(v.split())


@router.post("/auth/local/register", status_code=201)
def local_register(body: LocalRegister, request: Request):
    """Local demonstration only: create a CUSTOMER account and sign it in. The role is never taken from the request,
    so this can never create staff. Production sign-up is Supabase Auth."""
    s = request.app.state.settings
    if not s.local_auth_enabled:
        raise HTTPException(404, "Not found")
    tag = client_tag(request)
    request.app.state.limiter.check(f"register:{tag}", s.login_rate_limit_per_min,
                                    message="Too many attempts. Wait a minute and try again.")
    with request.app.state.db.session() as session:
        if session.scalar(select(AppUser.id).where(AppUser.email == body.email)):
            raise HTTPException(409, "An account with that email already exists. Sign in instead.")
        user = AppUser(email=body.email, full_name=body.full_name, role=perm.CUSTOMER, password_hash=hash_password(body.password))
        session.add(user)
        try:
            session.flush()
        except IntegrityError:
            raise HTTPException(409, "An account with that email already exists. Sign in instead.")
        token = issue_local_token(user.id, user.email, user.role, s.local_auth_secret, s.jwt_audience, s.local_auth_token_minutes)
        profile = {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role}
    return {"access_token": token, "token_type": "bearer", "expires_in": s.local_auth_token_minutes * 60,
            "user": profile, "notice": "Local demonstration account. Not for production."}


@router.post("/auth/local/login")
def local_login(body: LocalLogin, request: Request):
    s = request.app.state.settings
    if not s.local_auth_enabled:
        raise HTTPException(404, "Not found")
    tag = client_tag(request)
    request.app.state.limiter.check(f"login:{tag}", s.login_rate_limit_per_min,
                                    message="Too many sign-in attempts. Wait a minute and try again.")
    token = profile = None
    with request.app.state.db.session() as session:
        user = session.scalar(select(AppUser).where(AppUser.email == body.email.strip().lower()))
        ok = verify_password(body.password, user.password_hash if user else DUMMY_HASH)   # same work either way
        if user and ok and user.is_active:
            token = issue_local_token(user.id, user.email, user.role, s.local_auth_secret, s.jwt_audience,
                                      s.local_auth_token_minutes)
            profile = {"id": user.id, "email": user.email, "full_name": user.full_name, "role": user.role}
    if token is None:
        # Recorded AFTER the transaction closed: the events writer uses its own transaction.
        request.app.state.events.record("medium", "authentication", "auth.login_failed",
                                        "Failed local sign-in attempt", client_tag=tag,
                                        path=request.url.path, method="POST", status_code=401,
                                        correlation_id=correlation(request))
        raise HTTPException(401, "Incorrect email or password.")
    return {"access_token": token, "token_type": "bearer", "expires_in": s.local_auth_token_minutes * 60,
            "user": profile, "notice": "Local demonstration sign-in. Not for production."}


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    perms = sorted(p for p, roles in perm.PERMISSIONS.items() if user.role in roles)
    return {"id": user.id, "email": user.email, "role": user.role, "is_staff": user.is_staff, "permissions": perms}
