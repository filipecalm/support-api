import hashlib
import os
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

if not os.environ.get("DATABASE_URL"):
    raise RuntimeError("Set DATABASE_URL to a disposable PostgreSQL test database")

from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import AccessToken, User  # noqa: E402

if engine.url.database != "support_test" or os.environ.get("SUPPORT_ALLOW_TEST_RESET") != "1":
    raise RuntimeError("Tests require database support_test and SUPPORT_ALLOW_TEST_RESET=1")


@pytest.fixture(scope="session", autouse=True)
def least_privilege_runtime():
    password = secrets.token_urlsafe(32)
    with engine.begin() as connection:
        raw = connection.connection.driver_connection
        raw.execute(
            sql.SQL("CREATE ROLE support_runtime LOGIN PASSWORD {}").format(sql.Literal(password))
        )
        raw.execute("GRANT USAGE ON SCHEMA public TO support_runtime")
        raw.execute("GRANT SELECT, INSERT ON users TO support_runtime")
        raw.execute(
            "GRANT SELECT, UPDATE (window_start, requests) ON access_tokens TO support_runtime"
        )
        raw.execute(
            "GRANT SELECT, INSERT, UPDATE (window_start, requests) ON request_windows"
            " TO support_runtime"
        )
        raw.execute(
            "GRANT SELECT, INSERT, UPDATE (status, assignee_id, version) ON tickets TO support_runtime"
        )
        raw.execute("GRANT SELECT, INSERT ON comments, events TO support_runtime")
    runtime = create_engine(
        engine.url.set(username="support_runtime", password=password), hide_parameters=True
    )
    SessionLocal.configure(bind=runtime)
    yield
    SessionLocal.configure(bind=engine)
    runtime.dispose()
    with engine.begin() as connection:
        connection.execute(text("DROP OWNED BY support_runtime"))
        connection.execute(text("DROP ROLE support_runtime"))


@pytest.fixture(autouse=True)
def clean():
    with engine.begin() as db:
        db.execute(
            text(
                "TRUNCATE events, comments, tickets, access_tokens, request_windows, users CASCADE"
            )
        )


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def identities():
    result = {}
    with Session(engine) as db:
        for name, role in (
            ("alice", "CUSTOMER"),
            ("bob", "CUSTOMER"),
            ("agent", "AGENT"),
            ("admin", "ADMIN"),
        ):
            user = User(name=name, role=role)
            db.add(user)
            db.flush()
            secret = secrets.token_urlsafe(32)
            digest = hashlib.sha256(secret.encode()).hexdigest()
            db.add(
                AccessToken(
                    digest=digest,
                    user_id=user.id,
                    expires_at=datetime.now(UTC) + timedelta(hours=8),
                )
            )
            result[name] = {
                "id": str(user.id),
                "headers": {"Authorization": f"Bearer {secret}"},
                "digest": digest,
            }
        db.commit()
    return result


@pytest.fixture
def ticket(client, identities):
    response = client.post(
        "/v1/tickets",
        headers=identities["alice"]["headers"],
        json={
            "title": "Cannot open report",
            "description": "Report fails to open",
            "category": "Reports",
        },
    )
    assert response.status_code == 201
    return response.json()
