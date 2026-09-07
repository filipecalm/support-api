import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AccessToken, User

bearer = HTTPBearer(auto_error=False)


def authenticate(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> User:
    if credentials is None or not 40 <= len(credentials.credentials) <= 100:
        raise HTTPException(
            401, "Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}
        )
    digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    now = datetime.now(UTC)
    with SessionLocal.begin() as db:
        token = db.scalar(select(AccessToken).where(AccessToken.digest == digest).with_for_update())
        if token is None or token.revoked or token.expires_at <= now:
            raise HTTPException(
                401, "Invalid or expired access token", headers={"WWW-Authenticate": "Bearer"}
            )
        user = db.get(User, token.user_id)
        if user is None or not user.active:
            raise HTTPException(401, "Invalid or expired access token")
        if now - token.window_start >= timedelta(minutes=1):
            token.window_start, token.requests = now, 0
        if token.requests >= 120:
            raise HTTPException(429, "Request limit reached", headers={"Retry-After": "60"})
        token.requests += 1
        db.expunge(user)
        return user
