from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["OPEN", "IN_PROGRESS", "WAITING_CUSTOMER", "RESOLVED"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NewTicket(Input):
    title: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=5, max_length=10000)
    category: str = Field(min_length=2, max_length=60)
    priority: Literal["LOW", "NORMAL", "HIGH"] = "NORMAL"


class ChangeTicket(Input):
    expected_version: int = Field(ge=1, strict=True)
    status: Status | None = None
    assignee_id: UUID | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if "status" in self.model_fields_set and self.status is None:
            raise ValueError("status cannot be null")
        if not self.model_fields_set.intersection({"status", "assignee_id"}):
            raise ValueError("Provide a status or assignee change")
        return self


class NewComment(Input):
    body: str = Field(min_length=1, max_length=10000)
    internal: bool = Field(default=False, strict=True)


class Output(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TicketOut(Output):
    id: UUID
    customer_id: UUID
    assignee_id: UUID | None
    title: str
    description: str
    category: str
    priority: str
    status: str
    version: int
    created_at: datetime


class CommentOut(Output):
    id: UUID
    author_id: UUID
    body: str
    internal: bool
    created_at: datetime


class EventOut(Output):
    id: UUID
    actor_id: UUID
    action: str
    created_at: datetime
