from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from solution_copilot.application.requirement_schemas import ExtractionOutput
from solution_copilot.application.schemas import Input


class ConversationInput(Input):
    title: str = Field(default="需求澄清", min_length=1, max_length=200)


class MessageInput(Input):
    text: str = Field(min_length=1, max_length=4000)
    request_id: UUID
    epoch: int = Field(ge=0)


class AnswerInput(Input):
    conversation_id: UUID
    answer: str = Field(min_length=1, max_length=4000)
    version: int = Field(ge=1)
    profile_version: int = Field(ge=0)
    epoch: int = Field(ge=0)


class VersionInput(Input):
    version: int = Field(ge=1)


class ResetInput(Input):
    confirm: bool = False


class MemoryInput(Input):
    source_message_id: UUID
    scope: Literal["conversation", "project", "customer"]
    kind: Literal["fact", "preference", "decision", "constraint", "summary"] = "fact"
    content: str = Field(min_length=1, max_length=2000)


class MemoryEdit(VersionInput):
    content: str = Field(min_length=1, max_length=2000)
    status: Literal["proposed", "confirmed", "expired"]
    expires_at: datetime | None = None


class ChatOutput(ExtractionOutput):
    reply: str = Field(min_length=1, max_length=8000)


class ConversationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    title: str
    epoch: int


class MessageView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    seq: int
    epoch: int
    role: str
    content: list[dict]
    run_id: UUID | None
    model_info: dict
    created_at: datetime


class OutlineSection(BaseModel):
    id: str
    title: str


class WorkflowView(BaseModel):
    stage: str
    gate: int
    outline: list[OutlineSection]
    warnings: list[str]


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    conversation_id: UUID
    status: str
    attempts: int
    model_info: dict
    error_message: str | None
    workflow: WorkflowView | None = None


class ClarificationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    category: str
    question: str
    reason: str
    importance: str
    status: str
    answer: str | None
    source_message_id: UUID | None
    version: int


class MemoryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    scope: str
    kind: str
    content: str
    source_message_id: UUID
    conversation_id: UUID | None
    status: str
    expires_at: datetime | None
    version: int


class WorkspaceView(BaseModel):
    conversations: list[ConversationView]
    clarifications: list[ClarificationView]
    memories: list[MemoryView]
    writable: bool


class HistoryView(BaseModel):
    conversation: ConversationView
    messages: list[MessageView]
    next_after: int | None
    run: RunView | None
