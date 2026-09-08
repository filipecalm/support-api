import logging
import uuid
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.auth import authenticate
from app.config import host_allowlist, settings
from app.db import session
from app.models import Comment, Event, Ticket, User
from app.schemas import ChangeTicket, CommentOut, EventOut, NewComment, NewTicket, Status, TicketOut
from app.service import accessible, change, event, scope

app = FastAPI(
    title="Support API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url="/openapi.json" if settings().expose_docs else None,
)
DB = Annotated[Session, Depends(session)]
Identity = Annotated[User, Depends(authenticate)]
Page = Annotated[int, Query(ge=1, le=1000)]
Size = Annotated[int, Query(ge=1, le=100)]


class Boundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex

        async def secured(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"x-content-type-options", b"nosniff"),
                    (b"cache-control", b"no-store"),
                    (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'"),
                    (b"referrer-policy", b"no-referrer"),
                    (b"x-request-id", request_id.encode()),
                ]
            await send(message)

        headers = dict(scope["headers"])
        if scope["method"] in {"POST", "PATCH", "PUT"}:
            if headers.get(b"content-type", b"").split(b";")[0].strip() != b"application/json":
                return await JSONResponse({"detail": "Use application/json"}, 415)(
                    scope, receive, secured
                )
        if b"content-encoding" in headers:
            return await JSONResponse({"detail": "Encoded bodies are not supported"}, 415)(
                scope, receive, secured
            )
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 32768:
                return await JSONResponse({"detail": "Body exceeds 32 KiB"}, 413)(
                    scope, receive, secured
                )
            if not message.get("more_body", False):
                break

        async def buffered():
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        try:
            await self.app(scope, buffered, secured)
        except Exception as exc:
            logging.getLogger("support").error(
                "Request failed: request_id=%s exception_type=%s", request_id, type(exc).__name__
            )
            await JSONResponse({"detail": "Internal server error"}, 500)(scope, buffered, secured)


app.add_middleware(TrustedHostMiddleware, allowed_hosts=host_allowlist())
app.add_middleware(Boundary)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()]},
    )


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready(db: DB):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ready"}


@app.get("/v1/me")
def me(user: Identity):
    return {"id": user.id, "name": user.name, "role": user.role}


def page_result(db, query, model, page, size, table):
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    items = db.scalars(
        query.order_by(table.created_at, table.id).offset((page - 1) * size).limit(size)
    )
    return {
        "items": [model.model_validate(item) for item in items],
        "total": total,
        "page": page,
        "size": size,
    }


@app.post("/v1/tickets", response_model=TicketOut, status_code=201)
def create_ticket(payload: NewTicket, db: DB, user: Identity):
    if user.role != "CUSTOMER":
        raise HTTPException(403, "Only customers can create tickets")
    ticket = Ticket(customer_id=user.id, **payload.model_dump())
    db.add(ticket)
    db.flush()
    event(db, ticket, user, "CREATED")
    db.commit()
    return ticket


@app.get("/v1/tickets")
def list_tickets(
    db: DB,
    user: Identity,
    page: Page = 1,
    size: Size = 20,
    status: Status | None = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
):
    query = scope(user)
    if status:
        query = query.where(Ticket.status == status)
    if q:
        # Search only ticket text. Never search confidential notes for customer queries.
        query = query.where(
            Ticket.title.icontains(q, autoescape=True)
            | Ticket.description.icontains(q, autoescape=True)
        )
    return page_result(db, query, TicketOut, page, size, Ticket)


@app.get("/v1/tickets/{ticket_id}", response_model=TicketOut)
def get_ticket(ticket_id: uuid.UUID, db: DB, user: Identity):
    return accessible(db, user, ticket_id)


@app.patch("/v1/tickets/{ticket_id}", response_model=TicketOut)
def change_ticket(ticket_id: uuid.UUID, payload: ChangeTicket, db: DB, user: Identity):
    return change(db, user, ticket_id, payload)


@app.post("/v1/tickets/{ticket_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(ticket_id: uuid.UUID, payload: NewComment, db: DB, user: Identity):
    ticket = accessible(db, user, ticket_id)
    if payload.internal and user.role == "CUSTOMER":
        raise HTTPException(403, "Internal notes require staff access")
    comment = Comment(ticket_id=ticket.id, author_id=user.id, **payload.model_dump())
    db.add(comment)
    # Appending a note does not alter public ticket timestamps or version.
    event(db, ticket, user, "INTERNAL_NOTE" if payload.internal else "COMMENT", payload.internal)
    db.commit()
    return comment


@app.get("/v1/tickets/{ticket_id}/comments")
def comments(ticket_id: uuid.UUID, db: DB, user: Identity, page: Page = 1, size: Size = 20):
    accessible(db, user, ticket_id)
    query = select(Comment).where(Comment.ticket_id == ticket_id)
    if user.role == "CUSTOMER":
        query = query.where(Comment.internal.is_(False))
    return page_result(db, query, CommentOut, page, size, Comment)


@app.get("/v1/tickets/{ticket_id}/events")
def events(ticket_id: uuid.UUID, db: DB, user: Identity, page: Page = 1, size: Size = 20):
    accessible(db, user, ticket_id)
    query = select(Event).where(Event.ticket_id == ticket_id)
    if user.role == "CUSTOMER":
        query = query.where(Event.internal.is_(False))
    return page_result(db, query, EventOut, page, size, Event)
