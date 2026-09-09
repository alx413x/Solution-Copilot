from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from solution_copilot.application.schemas import Input

Category = Literal[
    "background",
    "pain_point",
    "goal",
    "functional",
    "non_functional",
    "integration",
    "data",
    "security_compliance",
    "constraint",
    "timeline_budget",
    "acceptance_metric",
    "risk",
]
Priority = Literal["must", "should", "could", "unknown"]
Status = Literal["proposed", "confirmed", "rejected", "conflicted"]
REQUIRED = (
    "background",
    "pain_point",
    "goal",
    "functional",
    "integration",
    "security_compliance",
    "constraint",
    "acceptance_metric",
)


class ItemInput(Input):
    category: Category
    title: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=4000)
    priority: Priority = "unknown"


class Candidate(ItemInput):
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    source_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=4000)
    related_id: UUID | None = None
    relation: Literal["new", "duplicate", "conflict"] = "new"

    @model_validator(mode="after")
    def relation_target(self):
        if (self.relation == "new") != (self.related_id is None):
            raise ValueError("duplicate/conflict requires an existing item id")
        return self


class ExtractionOutput(Input):
    summary: str = Field(max_length=4000)
    items: list[Candidate] = Field(max_length=100)


class ExtractionInput(Input):
    text: str = Field(default="", max_length=30000)
    document_ids: list[UUID] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def has_source(self):
        if not self.text and not self.document_ids:
            raise ValueError("A source is required")
        return self


class EditInput(Input):
    version: int = Field(ge=0)
    item_id: UUID | None = None
    item: ItemInput | None = None
    status: Literal["confirmed", "rejected"] | None = None
    summary: str | None = Field(default=None, max_length=4000)
    resolve_with: Literal["keep", "replace"] | None = None


class ConfirmInput(Input):
    version: int = Field(ge=0)


class SourceView(BaseModel):
    source_id: str
    type: Literal["document", "user", "message"]
    quote: str
    message_seq: int | None = None
    message_id: UUID | None = None
    conversation_id: UUID | None = None
    document_id: UUID | None = None
    title: str
    generation: int | None = None
    page_number: int | None = None
    section_path: list[str] = Field(default_factory=list)
    line_start: int | None = None
    line_end: int | None = None


class ItemView(ItemInput):
    id: UUID
    status: Status
    confidence: float | None
    sources: list[SourceView]
    edited: bool
    conflicts_with: list[UUID]


class ExtractionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: str
    attempts: int
    error_message: str | None
    model_info: dict


class ProfileView(BaseModel):
    project_id: UUID
    version: int
    summary: str
    items: list[ItemView]
    completeness_score: float
    missing_categories: list[str]
    confirmed_at: datetime | None
    writable: bool
    extraction: ExtractionView | None
