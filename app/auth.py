import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient, PyJWTError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import neon_auth_origin, neon_jwks_url
from app.db import SessionLocal
from app.models import AccessToken, RequestWindow, User

bearer = HTTPBearer(auto_error=False)
AUTH_HEADERS = {"WWW-Authenticate": "Bearer"}


def _unauthorized() -> HTTPException:
    return HTTPException(401, "Invalid or expired access token", headers=AUTH_HEADERS)


def _jwt_shaped(token: str) -> bool:
    parts = token.split(".")
    return len(parts) == 3 and all(parts)


@lru_cache
def _jwks_client() -> PyJWKClient:
    url = neon_jwks_url()
    if not url:
        raise RuntimeError("NEON_AUTH_JWKS_URL or NEON_AUTH_BASE_URL is required for JWT auth")
    return PyJWKClient(url, cache_keys=True, lifespan=3600)


def _enforce_window(db: Session, window: RequestWindow, now: datetime) -> None:
    if now - window.window_start >= timedelta(minutes=1):
        window.window_start, window.requests = now, 0
    if window.requests >= 120:
        raise HTTPException(429, "Request limit reached", headers={"Retry-After": "60"})
    window.requests += 1


def _rate_limit_user(db: Session, user_id: uuid.UUID, now: datetime) -> None:
    window = db.get(RequestWindow, user_id, with_for_update=True)
    if window is None:
        try:
            with db.begin_nested():
                db.add(RequestWindow(user_id=user_id, window_start=now, requests=0))
                db.flush()
        except IntegrityError:
            pass
        window = db.get(RequestWindow, user_id, with_for_update=True)
        if window is None:
            raise _unauthorized()
    _enforce_window(db, window, now)


def _authenticate_opaque(token: str) -> User:
    if not 40 <= len(token) <= 100:
        raise _unauthorized()
    digest = hashlib.sha256(token.encode()).hexdigest()
    now = datetime.now(UTC)
    with SessionLocal.begin() as db:
        row = db.scalar(select(AccessToken).where(AccessToken.digest == digest).with_for_update())
        if row is None or row.revoked or row.expires_at <= now:
            raise _unauthorized()
        user = db.get(User, row.user_id)
        if user is None or not user.active:
            raise _unauthorized()
        if now - row.window_start >= timedelta(minutes=1):
            row.window_start, row.requests = now, 0
        if row.requests >= 120:
            raise HTTPException(429, "Request limit reached", headers={"Retry-After": "60"})
        row.requests += 1
        db.expunge(user)
        return user


def _authenticate_jwt(token: str) -> User:
    if len(token) > 4096:
        raise _unauthorized()
    origin = neon_auth_origin()
    if not origin or not neon_jwks_url():
        raise _unauthorized()
    try:
        key = _jwks_client().get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            key.key,
            algorithms=["EdDSA"],
            issuer=origin,
            audience=origin,
        )
    except (PyJWTError, RuntimeError, ValueError):
        raise _unauthorized() from None
    if payload.get("banned") is True:
        raise _unauthorized()
    subject = payload.get("sub")
    try:
        neon_id = uuid.UUID(str(subject))
    except (TypeError, ValueError):
        raise _unauthorized() from None
    raw_name = str(payload.get("name") or payload.get("email") or "User").strip() or "User"
    name = raw_name[:100]
    email = payload.get("email")
    email_value = str(email).strip().lower()[:320] if email else None
    now = datetime.now(UTC)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.neon_auth_id == neon_id))
        if user is None:
            if email_value:
                conflict = db.scalar(select(User.id).where(User.email == email_value))
                if conflict is not None:
                    raise _unauthorized()
            user = User(
                name=name,
                role="CUSTOMER",
                active=True,
                neon_auth_id=neon_id,
                email=email_value,
            )
            try:
                with db.begin_nested():
                    db.add(user)
                    db.flush()
            except IntegrityError:
                user = db.scalar(select(User).where(User.neon_auth_id == neon_id))
                if user is None:
                    raise _unauthorized() from None
        if not user.active:
            raise _unauthorized()
        _rate_limit_user(db, user.id, now)
        db.expunge(user)
        return user


def authenticate(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None or not credentials.credentials:
        raise _unauthorized()
    token = credentials.credentials
    if _jwt_shaped(token):
        return _authenticate_jwt(token)
    return _authenticate_opaque(token)
