# HTTP contract

Base path: `/v1`. Send `Authorization: Bearer <token>` on every endpoint except `/health` and `/ready`. The bearer may be an opaque CLI token or a Neon Auth JWT (`authClient.token()`). Mutations use `application/json`; compressed request bodies are rejected. Maximum body: 32 KiB. Default limit: 120 authenticated requests per identity per minute, shared across app instances through PostgreSQL.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Process health |
| GET | `/ready` | Database readiness; generic 503 on failure |
| GET | `/v1/me` | Current identity and role |
| POST | `/v1/tickets` | Customer creates a ticket |
| GET | `/v1/tickets` | Authorized list, filters and search |
| GET | `/v1/tickets/{id}` | Authorized ticket detail |
| PATCH | `/v1/tickets/{id}` | Staff changes state/assignment; customer may reopen |
| POST | `/v1/tickets/{id}/comments` | Public reply or staff-only internal note |
| GET | `/v1/tickets/{id}/comments` | Visible comments with pagination |
| GET | `/v1/tickets/{id}/events` | Visible audit history with pagination |

List parameters: `page=1..1000`, `size=1..100` (default 20), ticket-only `status` and `q` (100 characters maximum). Search covers title and description only, treating SQL wildcard characters literally. Responses contain `items`, `total`, `page` and `size`. Ordering is creation time then UUID; this is offset pagination and concurrent inserts can affect page boundaries.

Create:

```json
{"title":"Report unavailable","description":"Monthly report does not load","category":"Reports","priority":"NORMAL"}
```

Priority: `LOW`, `NORMAL`, `HIGH`. The server sets customer, status and version; extra fields are rejected.

Change:

```json
{"expected_version":1,"status":"IN_PROGRESS","assignee_id":"<active-staff-uuid>"}
```

Omit `assignee_id` to preserve assignment; send `null` to unassign. A successful patch increments `version`. A stale version or invalid transition returns `409`. Reload the ticket and reconcile the change before retrying. The update and audit events commit atomically.

Transitions:

```text
OPEN -> IN_PROGRESS or RESOLVED
IN_PROGRESS -> WAITING_CUSTOMER or RESOLVED
WAITING_CUSTOMER -> IN_PROGRESS or RESOLVED
RESOLVED -> OPEN
```

Customers may only perform the last transition on their own tickets; there is no reopening time limit in this iteration.

Comment:

```json
{"body":"Investigation details for staff","internal":true}
```

`internal` defaults to false. Customers cannot create internal notes. Notes do not change public ticket version or timestamps. Internal comment events and assignment events are staff-only; public status changes and replies appear in customer history. The assigned staff UUID is public ticket metadata.

Errors: `401` missing/expired/revoked credential, `403` disallowed operation, `404` missing or inaccessible ticket, `409` conflict, `413` oversized body, `415` unsupported media, `422` invalid input, `429` rate limit. Error responses never echo submitted values. Do not render ticket/comment text as raw HTML in clients.

OpenAPI JSON is disabled by default; set `EXPOSE_DOCS=true` locally to enable `/openapi.json`. Interactive documentation is not served from third-party CDNs.
