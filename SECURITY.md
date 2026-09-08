# Security model and audit

## Scope and trust boundaries

This iteration is a single-organization API with operator-provisioned identities and short-lived bearer tokens. It does not implement browser login or claim production readiness. Customers are untrusted; staff can access all tickets. The operator, migration owner and database administrator are trusted.

| Threat | Implemented control | Regression evidence |
| --- | --- | --- |
| Access to another customer's ticket (BOLA/IDOR) | Ownership predicate before lookup, search, counting and pagination; uniform 404 | All detail/comment/history/write routes and list/search tested |
| Internal note disclosure | SQL visibility filter before count/limit; no note search; no public version/timestamp changes | Detail equality, counts, page contents, history and search tested |
| Privilege escalation / mass assignment | Extra input forbidden; roles assigned only by trusted CLI | Injected role/customer/status/assignee fields rejected |
| Lost updates | Atomic version-conditional UPDATE; status audit in same transaction | Two simultaneous HTTP requests produce one 200 and one 409, exactly one transition event |
| Token theft from database | 256-bit random bearer secrets, only SHA-256 digest stored; expiry and revocation | Expired/revoked/disabled identities rejected; CLI lifecycle tested |
| Request amplification | 32 KiB body bound, field bounds, bounded pages, SQL statement timeout, 120 requests/token/minute | Body/query limits and rate-limit responses tested |
| SQL injection | SQLAlchemy parameters and escaped literal substring search | Injection and wildcard probes tested |
| History tampering / excessive runtime privileges | Separate runtime role with no update/delete on comments/events, no user writes or DDL; only specific token/ticket columns updatable | Real PostgreSQL privilege checks, API tests run under restricted role |
| Sensitive error disclosure | Generic failures, validation omits input, error log contains only generated request ID and exception class | Injected secret-bearing failure absent from response/log |
| Credential exposure in source | Exclusive private token file creation, no CLI token output; ignored environment/token files | CLI output and refusal to overwrite an existing token tested |

The database owner can alter history. These audit events are immutable to the web runtime, not cryptographically tamper-proof. Assignment events are staff-only but the assignee UUID is intentionally visible ticket metadata. Token revocation prevents subsequent authentication; requests already authenticated may finish.

## Verification recorded 2026-09-07

- Python 3.12.14, native PostgreSQL 18.4 on Windows, bound to loopback, with a randomly generated temporary credential.
- 26 pytest tests passed, including restricted-role queries, concurrent updates and CLI issuance/revocation. The test database was stopped afterward.
- Alembic applied the initial migration; `alembic check` found no model/schema drift.
- Ruff lint/format and Bandit passed; pip check found no broken dependencies. The runtime lock-file audit also reported no known vulnerabilities. Compose configuration validation passed.
- `pip-audit` initially identified advisories affecting the virtual environment's bundled pip 25.0.1. Upgraded and pinned pip 26.2.1; the subsequent installed-environment audit reported no known vulnerabilities.
- Dependency lock files include exact versions and hashes. Audit findings are a dated observation, not a guarantee that future advisories will not appear.
- The test client currently emits two upstream deprecation warnings concerning HTTPX and AnyIO. Tests pass; warnings have not been suppressed.
- GitHub Actions and Docker configuration are provided. Remote CI, container build and public deployment have not been executed locally. Compose targets PostgreSQL 18.6; local native tests used 18.4.

## Deployment requirements still outside this local iteration

1. Use TLS at a reverse proxy, connection/header/body timeouts and an IP-based limit before authentication. The application's token limit does not stop unauthenticated floods. Disable access logging of sensitive URLs/headers and redact Authorization in observability tools.
2. Use separate schema-owner and runtime credentials. Apply `ops/runtime-grants.sql` to a newly provisioned, non-owner, non-superuser runtime role. Migrations and the administrative CLI use the owner credential through a separate process. Compose's development account owns the schema and is not a production runtime identity.
3. Configure exact allowed hostnames in `ALLOWED_HOSTS`; CORS is disabled. On Vercel, `VERCEL_URL`, `VERCEL_BRANCH_URL` and `VERCEL_PROJECT_PRODUCTION_URL` are merged into the allowlist so deployment and production aliases are not rejected as `Invalid host header`. Do not set `ALLOWED_HOSTS=["*"]`. Do not weaken origin policy to integrate the frontend. Design browser authentication first; do not store long-lived bearer credentials in localStorage.
4. Keep token files and environment files private, including Windows ACLs. Tokens are bearer credentials: possession grants access. The API accepts no authentication cookies, so its current authentication has no ambient-cookie CSRF surface. Reassess CSRF when browser sessions are introduced.
5. Define backup/restore, log retention, data deletion, operational monitoring and credential rotation policies. Expired tokens remain in the database until an operator removes them; a retention job is not implemented.
6. Validate the container image, pin a reviewed image digest and execute CI on the target Linux environment before release. No container vulnerability scan or external penetration test is claimed.

No attachments, outbound URL fetches, webhook delivery or email processing are implemented. Ticket/comment text is untrusted and must be rendered as text by future clients.

## References

- [FastAPI security dependencies](https://fastapi.tiangolo.com/tutorial/security/)
- [SQLAlchemy concurrency/versioning considerations](https://docs.sqlalchemy.org/en/20/orm/versioning.html) — this API uses an explicit conditional UPDATE rather than ORM version_id_col.

Report security issues privately to the repository maintainer. Do not include real tokens, personal ticket data or database credentials in a public issue.

## Vercel dependency manifest correction (2026-09-08)

The first Vercel deployment failed before application startup with `ModuleNotFoundError: fastapi`. The project metadata lacked runtime dependencies even though requirements.txt contained them. Runtime dependencies are now declared with exact versions in pyproject.toml; uv.lock records the resolved artifacts and hashes for the Vercel installation path. Python is bounded to 3.12, matching local verification, and the entrypoint is explicit.

A separate clean virtual environment installed with `uv sync --locked --no-dev` successfully imported app.main using a dummy database URL without connecting to a database. This verifies packaging and imports locally; Vercel deployment and Neon connectivity still require remote validation.

## Neon pooled readiness (2026-09-08)

`/health` succeeded on Vercel while `/ready` returned generic `503 Database unavailable`. Neon’s pooled endpoint rejects `statement_timeout` in the PostgreSQL startup `options` packet. The runtime still enforces a 5s statement timeout, but applies it with `SET` after connect so pooled and direct URLs both work. `DATABASE_URL` must use the `postgresql+psycopg://` dialect; plain `postgresql://` expects psycopg2, which is not installed.
