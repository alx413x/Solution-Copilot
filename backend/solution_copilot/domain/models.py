from datetime import datetime
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, foreign, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Record:
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Organization(Record, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)


class User(Record, Base):
    __tablename__ = "users"
    external_subject: Mapped[str] = mapped_column(String(255), unique=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(160))
    dev_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)


class Membership(Record, Base):
    __tablename__ = "memberships"
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(16))
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        CheckConstraint("role IN ('owner','member','viewer')"),
    )


class Customer(Record, Base):
    __tablename__ = "customers"
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    industry: Mapped[str] = mapped_column(String(120), default="")
    region: Mapped[str] = mapped_column(String(120), default="")
    company_size: Mapped[str] = mapped_column(String(80), default="")
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (UniqueConstraint("organization_id", "id"),)


class CustomerAccess(Record, Base):
    __tablename__ = "customer_access"
    organization_id: Mapped[UUID] = mapped_column()
    customer_id: Mapped[UUID] = mapped_column()
    user_id: Mapped[UUID] = mapped_column()
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "customer_id"], ["customers.organization_id", "customers.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "user_id"], ["memberships.organization_id", "memberships.user_id"]
        ),
        UniqueConstraint("organization_id", "customer_id", "user_id"),
    )


class Project(Record, Base):
    __tablename__ = "projects"
    organization_id: Mapped[UUID] = mapped_column(index=True)
    customer_id: Mapped[UUID] = mapped_column(index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(String(24), default="collecting")
    owner_user_id: Mapped[UUID] = mapped_column()
    owner: Mapped[User] = relationship(
        primaryjoin=lambda: foreign(Project.owner_user_id) == User.id, viewonly=True, lazy="joined"
    )

    @property
    def owner_display_name(self) -> str:
        return self.owner.display_name

    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    version: Mapped[int] = mapped_column(default=1)
    __mapper_args__ = {"version_id_col": version}
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "customer_id"], ["customers.organization_id", "customers.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "owner_user_id"],
            ["memberships.organization_id", "memberships.user_id"],
        ),
        UniqueConstraint("organization_id", "id"),
        CheckConstraint(
            "status IN ('collecting','researching','drafting','reviewing','completed','archived')"
        ),
    )


class Document(Record, Base):
    __tablename__ = "documents"
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    customer_id: Mapped[UUID | None] = mapped_column()
    project_id: Mapped[UUID | None] = mapped_column()
    scope: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(20), default="upload")
    mime_type: Mapped[str] = mapped_column(String(100))
    storage_key: Mapped[str] = mapped_column(String(255), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    data: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column()
    generation: Mapped[int] = mapped_column(default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        UniqueConstraint("organization_id", "id"),
        UniqueConstraint(
            "organization_id",
            "sha256",
            "scope",
            "customer_id",
            "project_id",
            name="uq_document_content_scope",
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["organization_id", "customer_id"], ["customers.organization_id", "customers.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        CheckConstraint(
            "(scope = 'organization' AND customer_id IS NULL AND project_id IS NULL) OR "
            "(scope = 'customer' AND customer_id IS NOT NULL AND project_id IS NULL) OR "
            "(scope = 'project' AND customer_id IS NOT NULL AND project_id IS NOT NULL)"
        ),
        CheckConstraint(
            "status IN ('uploaded','parsing','parsed','indexing','ready','failed','disabled')"
        ),
    )


class DocumentChunk(Record, Base):
    __tablename__ = "document_chunks"
    organization_id: Mapped[UUID] = mapped_column()
    document_id: Mapped[UUID] = mapped_column(index=True)
    ordinal: Mapped[int] = mapped_column()
    generation: Mapped[int] = mapped_column()
    content: Mapped[str] = mapped_column()
    token_count: Mapped[int | None] = mapped_column()
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    embedding_profile: Mapped[str | None] = mapped_column(String(200))
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    page_number: Mapped[int | None] = mapped_column()
    section_path: Mapped[list] = mapped_column(JSONB)
    data: Mapped[dict] = mapped_column("metadata", JSONB)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "document_id"], ["documents.organization_id", "documents.id"]
        ),
        UniqueConstraint("document_id", "generation", "ordinal"),
        Index("ix_chunks_search_vector", "search_vector", postgresql_using="gin"),
    )


class RequirementProfile(Record, Base):
    __tablename__ = "requirement_profiles"
    organization_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID] = mapped_column(unique=True)
    version: Mapped[int] = mapped_column(default=1)
    summary: Mapped[str] = mapped_column(default="")
    summary_edited: Mapped[bool] = mapped_column(default=False)
    # ponytail: atomic project-sized JSON; normalize items if profiles outgrow 200 items.
    items: Mapped[list] = mapped_column(JSONB, default=list)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
    )


class RequirementExtraction(Record, Base):
    __tablename__ = "requirement_extractions"
    organization_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID] = mapped_column(index=True)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB)
    model_info: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column()
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')"),
        Index(
            "uq_active_requirement_extraction",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )


class Job(Record, Base):
    __tablename__ = "jobs"
    organization_id: Mapped[UUID] = mapped_column()
    resource_id: Mapped[UUID] = mapped_column(index=True)
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    job_type: Mapped[str] = mapped_column(String(40), default="document.parse")
    resource_type: Mapped[str] = mapped_column(String(20), default="document")
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[int] = mapped_column(default=0)
    attempts: Mapped[int] = mapped_column(default=0)
    generation: Mapped[int] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dispatch_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column()
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "resource_id"], ["documents.organization_id", "documents.id"]
        ),
        UniqueConstraint("resource_id", "generation"),
        CheckConstraint("status IN ('queued','running','succeeded','failed','cancelled')"),
        CheckConstraint("progress BETWEEN 0 AND 100"),
    )


class Conversation(Record, Base):
    __tablename__ = "conversations"
    organization_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(200))
    epoch: Mapped[int] = mapped_column(default=0)
    next_seq: Mapped[int] = mapped_column(default=1)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        UniqueConstraint("organization_id", "id"),
    )


class Message(Record, Base):
    __tablename__ = "messages"
    organization_id: Mapped[UUID] = mapped_column()
    conversation_id: Mapped[UUID] = mapped_column(index=True)
    epoch: Mapped[int] = mapped_column()
    seq: Mapped[int] = mapped_column()
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[list] = mapped_column(JSONB)
    run_id: Mapped[UUID | None] = mapped_column(ForeignKey("generation_runs.id"))
    model_info: Mapped[dict] = mapped_column(JSONB, default=dict)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
        ),
        UniqueConstraint("conversation_id", "seq"),
        CheckConstraint("role IN ('user','assistant','system','tool')"),
    )


class GenerationRun(Record, Base):
    __tablename__ = "generation_runs"
    organization_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID] = mapped_column()
    conversation_id: Mapped[UUID] = mapped_column()
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    request_id: Mapped[UUID] = mapped_column()
    status: Mapped[str] = mapped_column(String(20), default="queued")
    attempts: Mapped[int] = mapped_column(default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict] = mapped_column(JSONB)
    # ponytail: <=230 bounded events per run; normalize for token-level live streaming.
    events: Mapped[list] = mapped_column(JSONB, default=list)
    model_info: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_message: Mapped[str | None] = mapped_column()
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
        ),
        UniqueConstraint("conversation_id", "request_id"),
        CheckConstraint(
            "status IN ('queued','running','waiting_user','succeeded','failed','cancelled')"
        ),
        Index(
            "uq_active_generation_run",
            "project_id",
            unique=True,
            postgresql_where=text("status IN ('queued','running')"),
        ),
    )


class Clarification(Record, Base):
    __tablename__ = "clarifications"
    organization_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID] = mapped_column()
    category: Mapped[str] = mapped_column(String(40))
    question: Mapped[str] = mapped_column()
    reason: Mapped[str] = mapped_column()
    importance: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="open")
    answer: Mapped[str | None] = mapped_column()
    source_message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id"))
    answered_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        UniqueConstraint("project_id", "category"),
        CheckConstraint("status IN ('open','answered','skipped')"),
        CheckConstraint("importance IN ('required','recommended')"),
    )


class Memory(Record, Base):
    __tablename__ = "memories"
    organization_id: Mapped[UUID] = mapped_column()
    customer_id: Mapped[UUID] = mapped_column()
    project_id: Mapped[UUID | None] = mapped_column()
    conversation_id: Mapped[UUID | None] = mapped_column()
    scope: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column()
    source_message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id"))
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(default=1)
    __table_args__ = (
        ForeignKeyConstraint(
            ["organization_id", "customer_id"], ["customers.organization_id", "customers.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "project_id"], ["projects.organization_id", "projects.id"]
        ),
        ForeignKeyConstraint(
            ["organization_id", "conversation_id"],
            ["conversations.organization_id", "conversations.id"],
        ),
        CheckConstraint(
            "(scope='customer' AND project_id IS NULL AND conversation_id IS NULL) OR "
            "(scope='project' AND project_id IS NOT NULL AND conversation_id IS NULL) OR "
            "(scope='conversation' AND project_id IS NOT NULL AND conversation_id IS NOT NULL)"
        ),
        CheckConstraint("status IN ('proposed','confirmed','expired')"),
    )


class AuditEvent(Record, Base):
    __tablename__ = "audit_events"
    organization_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"))
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    resource_id: Mapped[UUID] = mapped_column()
    data: Mapped[dict] = mapped_column(JSONB)
