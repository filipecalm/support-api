from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine
from app.main import app
from app.models import AccessToken, User


def test_authentication_required(client):
    for headers in ({}, {"Authorization": "Bearer invalid"}, {"Cookie": "session=fake"}):
        assert client.get("/v1/tickets", headers=headers).status_code == 401


@pytest.mark.parametrize("condition", ["expired", "revoked", "disabled"])
def test_unusable_credentials(client, identities, condition):
    with Session(engine) as db:
        token = db.get(AccessToken, identities["alice"]["digest"])
        if condition == "expired":
            token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif condition == "revoked":
            token.revoked = True
        else:
            db.get(User, token.user_id).active = False
        db.commit()
    assert client.get("/v1/me", headers=identities["alice"]["headers"]).status_code == 401


def test_bola_across_all_ticket_routes(client, identities, ticket):
    headers = identities["bob"]["headers"]
    base = f"/v1/tickets/{ticket['id']}"
    for path in (base, base + "/comments", base + "/events"):
        assert client.get(path, headers=headers).status_code == 404
    assert (
        client.post(base + "/comments", headers=headers, json={"body": "Intrusion"}).status_code
        == 404
    )
    assert (
        client.patch(
            base, headers=headers, json={"expected_version": 1, "status": "RESOLVED"}
        ).status_code
        == 404
    )
    assert client.get("/v1/tickets", headers=headers).json()["total"] == 0
    assert client.get("/v1/tickets?q=report", headers=headers).json()["total"] == 0
    assert client.get(f"/v1/tickets/{uuid4()}", headers=headers).status_code == 404


def test_internal_notes_no_content_count_history_search_or_version_leak(client, identities, ticket):
    base = f"/v1/tickets/{ticket['id']}"
    customer, staff = identities["alice"]["headers"], identities["agent"]["headers"]
    before = client.get(base, headers=customer).json()
    before_events = client.get(base + "/events", headers=customer).json()
    marker = "CONFIDENTIAL-MARKER-123"
    assert (
        client.post(
            base + "/comments", headers=staff, json={"body": marker, "internal": True}
        ).status_code
        == 201
    )
    assert client.get(base, headers=customer).json() == before
    assert client.get(base + "/events", headers=customer).json() == before_events
    notes = client.get(base + "/comments?size=1", headers=customer).json()
    assert notes["total"] == 0 and notes["items"] == []
    assert client.get(f"/v1/tickets?q={marker}", headers=customer).json()["total"] == 0
    assert marker in client.get(base + "/comments", headers=staff).text
    assert client.get(base + "/events", headers=staff).json()["total"] == 2
    assert (
        client.post(base + "/comments", headers=customer, json={"body": "Public reply"}).status_code
        == 201
    )
    visible = client.get(base + "/comments?size=1", headers=customer).json()
    assert visible["total"] == 1 and visible["items"][0]["body"] == "Public reply"
    assert marker not in str(visible)


@pytest.mark.parametrize(
    "payload",
    [
        {"body": "Private attempt", "internal": True},
    ],
)
def test_customer_cannot_create_internal_note(client, identities, ticket, payload):
    assert (
        client.post(
            f"/v1/tickets/{ticket['id']}/comments",
            json=payload,
            headers=identities["alice"]["headers"],
        ).status_code
        == 403
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"role": "ADMIN"},
        {"customer_id": str(uuid4())},
        {"status": "RESOLVED"},
        {"assignee_id": str(uuid4())},
    ],
)
def test_mass_assignment_rejected(client, identities, extra):
    payload = {
        "title": "Valid title",
        "description": "Valid description",
        "category": "General",
        **extra,
    }
    response = client.post("/v1/tickets", headers=identities["alice"]["headers"], json=payload)
    assert response.status_code == 422
    assert "input" not in response.text


def test_status_workflow_and_reopening(client, identities, ticket):
    base = f"/v1/tickets/{ticket['id']}"
    customer, staff = identities["alice"]["headers"], identities["agent"]["headers"]
    assert (
        client.patch(
            base, headers=customer, json={"expected_version": 1, "status": "RESOLVED"}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            base, headers=staff, json={"expected_version": 1, "status": "WAITING_CUSTOMER"}
        ).status_code
        == 409
    )
    for version, status in enumerate(["IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED"], start=1):
        response = client.patch(
            base, headers=staff, json={"expected_version": version, "status": status}
        )
        assert response.status_code == 200
        assert response.json()["version"] == version + 1
    assert (
        client.patch(
            base, headers=customer, json={"expected_version": 4, "status": "OPEN"}
        ).status_code
        == 200
    )


def test_assignment_and_stale_update(client, identities, ticket):
    base = f"/v1/tickets/{ticket['id']}"
    headers = identities["admin"]["headers"]
    assert (
        client.patch(
            base,
            headers=headers,
            json={"expected_version": 1, "assignee_id": identities["alice"]["id"]},
        ).status_code
        == 422
    )
    response = client.patch(
        base,
        headers=headers,
        json={"expected_version": 1, "assignee_id": identities["agent"]["id"]},
    )
    assert response.status_code == 200
    assert response.json()["assignee_id"] == identities["agent"]["id"]
    assert (
        client.patch(
            base, headers=headers, json={"expected_version": 1, "status": "RESOLVED"}
        ).status_code
        == 409
    )


def test_concurrent_edits_have_one_winner_and_one_audit_event(client, identities, ticket):
    barrier = Barrier(2)

    def edit(name):
        with TestClient(app) as connection:
            barrier.wait(timeout=5)
            return connection.patch(
                f"/v1/tickets/{ticket['id']}",
                headers=identities[name]["headers"],
                json={"expected_version": 1, "status": "IN_PROGRESS"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(edit, ["agent", "admin"]))
    assert sorted(results) == [200, 409]
    events = client.get(
        f"/v1/tickets/{ticket['id']}/events", headers=identities["admin"]["headers"]
    ).json()
    assert events["total"] == 2


def test_sql_injection_and_wildcards_are_literal(client, identities, ticket):
    for value in ("' OR 1=1 --", "%", "_"):
        response = client.get(
            "/v1/tickets", params={"q": value}, headers=identities["alice"]["headers"]
        )
        assert response.status_code == 200 and response.json()["total"] == 0


@pytest.mark.parametrize(
    "query", ["size=101", "page=0", "page=1001", "status=UNKNOWN", "q=" + "x" * 101]
)
def test_bounded_queries(client, identities, query):
    assert (
        client.get("/v1/tickets?" + query, headers=identities["alice"]["headers"]).status_code
        == 422
    )


def test_boundary(client, identities):
    headers = identities["alice"]["headers"]
    assert client.post("/v1/tickets", headers=headers, content="plain").status_code == 415
    assert (
        client.post(
            "/v1/tickets",
            headers={**headers, "Content-Type": "application/json"},
            content=b"x" * 32769,
        ).status_code
        == 413
    )
    assert client.get("/health", headers={"Host": "attacker.example"}).status_code == 400
    response = client.get("/health", headers={"X-Request-ID": "attacker"})
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-request-id"] != "attacker"
    assert client.get("/openapi.json").status_code == 404
    assert (
        "access-control-allow-origin"
        not in client.get("/health", headers={"Origin": "https://evil.test"}).headers
    )


def test_ready_and_statement_timeout(client):
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}
    with engine.connect() as connection:
        assert connection.execute(text("SHOW statement_timeout")).scalar() == "5s"


def test_host_allowlist_includes_vercel_urls(monkeypatch):
    from app.config import host_allowlist

    monkeypatch.setenv("VERCEL_URL", "support-nzbnnw2i8-almeidatech92.vercel.app")
    monkeypatch.setenv("VERCEL_PROJECT_PRODUCTION_URL", "support-api-three.vercel.app")
    hosts = host_allowlist()
    assert "support-nzbnnw2i8-almeidatech92.vercel.app" in hosts
    assert "support-api-three.vercel.app" in hosts
    assert "attacker.example" not in hosts


def test_neon_jwt_provisions_customer_only(client, monkeypatch):
    from uuid import uuid4

    import jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import app.auth as auth

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    neon_id = uuid4()
    origin = "https://auth.example.test"
    token = jwt.encode(
        {
            "sub": str(neon_id),
            "name": "Neon Customer",
            "email": "neon-customer@example.test",
            "role": "authenticated",
            "banned": False,
            "iss": origin,
            "aud": origin,
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "test-key"},
    )

    class Key:
        key = public_key

    class Client:
        def get_signing_key_from_jwt(self, value):
            assert value == token
            return Key()

    monkeypatch.setattr(auth, "_jwks_client", lambda: Client())
    monkeypatch.setattr(auth, "neon_auth_origin", lambda: origin)
    monkeypatch.setattr(auth, "neon_jwks_url", lambda: f"{origin}/.well-known/jwks.json")

    headers = {"Authorization": f"Bearer {token}"}
    me = client.get("/v1/me", headers=headers)
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "CUSTOMER"
    assert body["name"] == "Neon Customer"
    with Session(engine) as db:
        user = db.get(User, body["id"])
        assert user.neon_auth_id == neon_id
        assert user.email == "neon-customer@example.test"
        assert user.role == "CUSTOMER"


def test_neon_jwt_rejects_bad_signature_and_banned(client, monkeypatch):
    from uuid import uuid4

    import jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import app.auth as auth

    private_key = Ed25519PrivateKey.generate()
    other_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    origin = "https://auth.example.test"

    class Key:
        key = public_key

    class Client:
        def get_signing_key_from_jwt(self, value):
            return Key()

    monkeypatch.setattr(auth, "_jwks_client", lambda: Client())
    monkeypatch.setattr(auth, "neon_auth_origin", lambda: origin)
    monkeypatch.setattr(auth, "neon_jwks_url", lambda: f"{origin}/.well-known/jwks.json")

    bad = jwt.encode(
        {
            "sub": str(uuid4()),
            "name": "X",
            "email": "x@example.test",
            "iss": origin,
            "aud": origin,
        },
        other_key,
        algorithm="EdDSA",
        headers={"kid": "test-key"},
    )
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401

    banned = jwt.encode(
        {
            "sub": str(uuid4()),
            "name": "Banned",
            "email": "banned@example.test",
            "banned": True,
            "iss": origin,
            "aud": origin,
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "test-key"},
    )
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {banned}"}).status_code == 401


def test_linked_neon_agent_keeps_staff_role(client, monkeypatch):
    from uuid import uuid4

    import jwt
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    import app.auth as auth

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    neon_id = uuid4()
    origin = "https://auth.example.test"
    with Session(engine) as db:
        agent = User(
            name="Staff",
            role="AGENT",
            neon_auth_id=neon_id,
            email="agent@example.test",
        )
        db.add(agent)
        db.commit()
        agent_id = str(agent.id)

    token = jwt.encode(
        {
            "sub": str(neon_id),
            "name": "Staff",
            "email": "agent@example.test",
            "iss": origin,
            "aud": origin,
        },
        private_key,
        algorithm="EdDSA",
        headers={"kid": "test-key"},
    )

    class Key:
        key = public_key

    class Client:
        def get_signing_key_from_jwt(self, value):
            return Key()

    monkeypatch.setattr(auth, "_jwks_client", lambda: Client())
    monkeypatch.setattr(auth, "neon_auth_origin", lambda: origin)
    monkeypatch.setattr(auth, "neon_jwks_url", lambda: f"{origin}/.well-known/jwks.json")

    me = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json() == {"id": agent_id, "name": "Staff", "role": "AGENT"}


def test_rate_limit_enforced(client, identities):
    with Session(engine) as db:
        token = db.get(AccessToken, identities["alice"]["digest"])
        token.requests = 120
        db.commit()
    response = client.get("/v1/me", headers=identities["alice"]["headers"])
    assert response.status_code == 429 and response.headers["retry-after"] == "60"


def test_runtime_cannot_erase_audit_or_escalate_role(identities, ticket):
    for statement in (
        "DELETE FROM events",
        "UPDATE users SET role='ADMIN'",
        "DROP TABLE tickets",
        "UPDATE access_tokens SET expires_at = now() + interval '1 year'",
        "UPDATE tickets SET customer_id = customer_id",
    ):
        with SessionLocal() as db, pytest.raises(DBAPIError):
            db.execute(text(statement))


def test_credentials_are_hashed(identities):
    with Session(engine) as db:
        token = db.scalar(
            select(AccessToken).where(AccessToken.digest == identities["alice"]["digest"])
        )
        assert len(token.digest) == 64
        assert token.digest not in identities["alice"]["headers"]["Authorization"]


def test_unexpected_error_is_sanitized_and_not_cacheable(client, caplog):
    from app.auth import authenticate

    def failure():
        raise RuntimeError("SENSITIVE-EXCEPTION-CONTENT")

    app.dependency_overrides[authenticate] = failure
    try:
        response = client.get("/v1/me")
        assert response.status_code == 500
        assert response.json() == {"detail": "Internal server error"}
        assert response.headers["cache-control"] == "no-store"
        assert "SENSITIVE-EXCEPTION-CONTENT" not in response.text + caplog.text
    finally:
        app.dependency_overrides.clear()


def test_cli_issue_revoke_and_exclusive_file_creation(client, identities, tmp_path):
    import subprocess
    import sys

    output = tmp_path / "access.token"
    command = [
        sys.executable,
        "-m",
        "app.cli",
        "issue-token",
        "--user",
        identities["alice"]["id"],
        "--output",
        str(output),
        "--hours",
        "1",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=15)
    secret = output.read_text()
    assert secret not in result.stdout + result.stderr
    headers = {"Authorization": f"Bearer {secret}"}
    assert client.get("/v1/me", headers=headers).status_code == 200
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode != 0 and output.read_text() == secret
    subprocess.run(
        [sys.executable, "-m", "app.cli", "revoke-tokens", "--user", identities["alice"]["id"]],
        capture_output=True,
        check=True,
        timeout=15,
    )
    assert client.get("/v1/me", headers=headers).status_code == 401
