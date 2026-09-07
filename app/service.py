from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import Event, Ticket, User
from app.schemas import ChangeTicket

TRANSITIONS = {
    "OPEN": {"IN_PROGRESS", "RESOLVED"},
    "IN_PROGRESS": {"WAITING_CUSTOMER", "RESOLVED"},
    "WAITING_CUSTOMER": {"IN_PROGRESS", "RESOLVED"},
    "RESOLVED": {"OPEN"},
}


def scope(user: User):
    query = select(Ticket)
    return query.where(Ticket.customer_id == user.id) if user.role == "CUSTOMER" else query


def accessible(db: Session, user: User, ticket_id: UUID) -> Ticket:
    ticket = db.scalar(scope(user).where(Ticket.id == ticket_id))
    if ticket is None:
        raise HTTPException(404, "Ticket not found")
    return ticket


def event(db: Session, ticket: Ticket, user: User, action: str, internal: bool = False):
    db.add(Event(ticket_id=ticket.id, actor_id=user.id, action=action, internal=internal))


def change(db: Session, user: User, ticket_id: UUID, payload: ChangeTicket) -> Ticket:
    ticket = accessible(db, user, ticket_id)
    assignment = "assignee_id" in payload.model_fields_set
    if user.role == "CUSTOMER" and (
        assignment or ticket.status != "RESOLVED" or payload.status != "OPEN"
    ):
        raise HTTPException(403, "Customers may only reopen resolved tickets")
    if ticket.version != payload.expected_version:
        raise HTTPException(409, "Ticket changed; reload before retrying")
    values = {"version": ticket.version + 1}
    if payload.status is not None:
        if payload.status not in TRANSITIONS[ticket.status]:
            raise HTTPException(409, "Invalid status transition")
        values["status"] = payload.status
    if assignment:
        if payload.assignee_id is not None:
            assignee = db.get(User, payload.assignee_id)
            if assignee is None or not assignee.active or assignee.role not in {"AGENT", "ADMIN"}:
                raise HTTPException(422, "Assignee must be an active staff member")
        values["assignee_id"] = payload.assignee_id
    result = db.execute(
        update(Ticket)
        .where(Ticket.id == ticket.id, Ticket.version == payload.expected_version)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Ticket changed; reload before retrying")
    if payload.status:
        event(db, ticket, user, f"STATUS:{ticket.status}->{payload.status}")
    if assignment:
        event(db, ticket, user, f"ASSIGNED:{payload.assignee_id or 'NONE'}", internal=True)
    db.commit()
    db.refresh(ticket)
    return ticket
