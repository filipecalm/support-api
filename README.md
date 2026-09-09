# Support API

A Python support-ticket API designed to make authorization and concurrency decisions visible in code and tests. Built with FastAPI, SQLAlchemy 2, PostgreSQL and Alembic.

**First working iteration:** customers open tickets, staff triage them, and internal notes stay confidential across detail, search, pagination and audit history. This repository is the backend for a future Vue support dashboard.

## Features

- Customer, agent and admin identities; explicit ownership checks on every ticket endpoint.
- Ticket creation, categories, priorities, search and bounded pagination.
- Assignment to active staff and validated status transitions.
- Optimistic concurrency: stale changes return `409` instead of overwriting another agent's work.
- Public replies and confidential internal notes, with visibility enforced in SQL.
- Transactional audit events; restricted runtime database role cannot modify or delete history.
- Expiring opaque access tokens, SHA-256 digests at rest, revocation and database-backed rate limits.
- Real PostgreSQL tests, dependency hashes, static security analysis and CI configuration.

## Run locally (PowerShell)

Requires Python 3.12 and Docker Compose. Commands assume the repository root.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --require-hashes -r requirements-dev.txt
Copy-Item .env.example .env
docker compose up -d --wait postgres
python -m alembic upgrade head
python -m app.cli create-user --name 'Demo Customer' --role CUSTOMER
python -m app.cli create-user --name 'Demo Agent' --role AGENT
```

Use a returned user UUID to issue a token. The command writes a new file and never prints the credential:

```powershell
python -m app.cli issue-token --user '<USER_UUID>' --output demo.token --hours 8
python -m uvicorn app.main:app --host 127.0.0.1 --no-access-log --no-proxy-headers --limit-concurrency 100
```

In another terminal, create a ticket:

```powershell
$headers = @{ Authorization = 'Bearer ' + (Get-Content .\demo.token -Raw) }
$body = @{ title='Report unavailable'; description='The monthly report does not load'; category='Reports'; priority='NORMAL' } | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8000/v1/tickets -Method Post -Headers $headers -ContentType application/json -Body $body
```

Revoke all tokens for a user with `python -m app.cli revoke-tokens --user '<USER_UUID>'`.
Tokens last 8 hours by default, at most 24 hours. Use a private directory for token files; on Windows, protect its ACL. `.token` files and `.env` are ignored by Git. Never paste tokens into URLs, screenshots or issue reports.

## Vue dashboard (`web/`)

```powershell
cd web
Copy-Item .env.example .env
npm install
npm run dev
```

Sign up in the UI (Neon Auth). The API auto-provisions a `CUSTOMER`. Promote staff with the owner DB URL:

```powershell
python -m app.cli link-neon --user '<SUPPORT_USER_UUID>' --neon-auth-id '<NEON_AUTH_USER_UUID>' --email 'agent@example.com'
python -m app.cli set-role --user '<SUPPORT_USER_UUID>' --role AGENT
```

Set API env `NEON_AUTH_BASE_URL`, `NEON_AUTH_JWKS_URL`, and `ALLOWED_ORIGINS` (exact frontend origins). Deploy `web/` as its own Vercel project; add the production origin with `neon neon-auth domain add https://<front-host>`.

## Contract and design

See [API.md](API.md) for endpoint examples and [SECURITY.md](SECURITY.md) for the threat model, audit evidence and deployment boundaries.

`app/main.py` handles HTTP, `service.py` enforces ownership and transitions, `auth.py` validates credentials, `schemas.py` defines strict input/output contracts and `models.py` defines persistence. Alembic owns schema changes; startup never creates tables.

This iteration serves one support organization. All agents and admins may triage all tickets. Customers see only their own tickets. Role provisioning is an operator action; admin does not yet have additional HTTP capabilities beyond agent.

## Verification

Tests deliberately erase the `support_test` database. They refuse to run without the exact database name and the explicit reset flag. Never use a production connection. The fixture creates a restricted runtime role; the test setup credential therefore needs role creation privileges in this disposable database.

```powershell
docker compose --profile test up -d --wait test-db
$env:DATABASE_URL='postgresql+psycopg://support_test:local-development-only@127.0.0.1:55441/support_test'
$env:SUPPORT_ALLOW_TEST_RESET='1'
$env:ALLOWED_HOSTS='["testserver","localhost","127.0.0.1"]'
python -m alembic upgrade head
python -m alembic check
python -m pytest -q
python -m ruff check --config pyproject.toml app tests migrations
python -m ruff format --config pyproject.toml --check app tests migrations
python -m bandit -r app -q
python -m pip_audit --progress-spinner off
python -m pip_audit -r requirements.txt --require-hashes --disable-pip --progress-spinner off
Remove-Item Env:DATABASE_URL, Env:SUPPORT_ALLOW_TEST_RESET, Env:ALLOWED_HOSTS
```

If you changed the example database password, update the test connection accordingly. URL-encode special characters in connection credentials.

Update lock files intentionally and review audit results:

```powershell
python -m piptools compile --allow-unsafe --strip-extras --generate-hashes --no-emit-index-url -o requirements.txt requirements.in
python -m piptools compile --allow-unsafe --strip-extras --generate-hashes --no-emit-index-url -o requirements-dev.txt requirements-dev.in
```

## Next iterations

- Vue dashboard under `web/` with Neon Auth JWT → Support API identity mapping (this iteration).
- SLA policy, background processing and notifications with retry/idempotency tests.
- Operational metrics, deployment hardening and public demo data.

Attachments, outbound webhooks, email delivery, multitenancy and password storage are outside this iteration. No public deployment has been performed.

For Vercel, runtime dependencies are declared in pyproject.toml and locked in uv.lock. After intentional dependency changes, update both the pip-tools lock files and uv.lock. The configured entrypoint is app.main:app and Python is restricted to 3.12.
