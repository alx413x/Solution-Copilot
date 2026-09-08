from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from solution_copilot.application import documents as service
from solution_copilot.application.errors import AppError, missing
from solution_copilot.config import get_settings
from solution_copilot.domain.models import Document, DocumentChunk, Job
from solution_copilot.infrastructure import documents as storage
from sqlalchemy import select

from apps.api.auth import IdentityDep, SessionDep

router = APIRouter(prefix="/api/v1", tags=["documents"])


class JobView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    resource_id: UUID
    job_type: str
    resource_type: str
    status: str
    progress: int
    attempts: int
    generation: int
    error_code: str | None
    error_message: str | None
    updated_at: datetime


class DocumentView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    organization_id: UUID
    customer_id: UUID | None
    project_id: UUID | None
    scope: str
    title: str
    source_type: str
    mime_type: str
    sha256: str
    status: str
    generation: int
    metadata: dict = Field(validation_alias="data")
    error_code: str | None
    error_message: str | None
    created_at: datetime
    job: JobView | None = None


class UploadView(BaseModel):
    document: DocumentView
    job: JobView
    duplicate: bool


class DocumentList(BaseModel):
    items: list[DocumentView]
    next_cursor: UUID | None


class ChunkView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    document_id: UUID
    ordinal: int
    generation: int
    content: str
    token_count: int | None
    page_number: int | None
    section_path: list[str]
    metadata: dict = Field(validation_alias="data")


class ChunkList(BaseModel):
    items: list[ChunkView]
    next_offset: int | None


def view(session, doc):
    result = DocumentView.model_validate(doc)
    job = service.latest_job(session, doc)
    result.job = JobView.model_validate(job) if job else None
    return result


@router.post("/documents", response_model=UploadView, status_code=202)
def upload(
    session: SessionDep,
    identity: IdentityDep,
    file: Annotated[UploadFile, File()],
    scope: Annotated[str, Form()],
    customer_id: Annotated[UUID | None, Form()] = None,
    project_id: Annotated[UUID | None, Form()] = None,
):
    try:
        data = file.file.read(get_settings().upload_max_bytes + 1)
        doc, job, duplicate = service.upload(
            session,
            identity,
            scope,
            customer_id,
            project_id,
            file.filename or "",
            file.content_type,
            data,
        )
        return UploadView(
            document=view(session, doc), job=JobView.model_validate(job), duplicate=duplicate
        )
    finally:
        file.file.close()


@router.get("/documents", response_model=DocumentList)
def documents(
    session: SessionDep,
    identity: IdentityDep,
    scope: Literal["organization", "customer", "project"] | None = None,
    customer_id: UUID | None = None,
    project_id: UUID | None = None,
    cursor: UUID | None = None,
    limit: int = Query(30, ge=1, le=100),
):
    query = select(Document).where(*service.document_scope(identity))
    for column, value in [
        (Document.scope, scope),
        (Document.customer_id, customer_id),
        (Document.project_id, project_id),
    ]:
        if value is not None:
            query = query.where(column == value)
    if cursor:
        query = query.where(Document.id > cursor)
    items = list(session.scalars(query.order_by(Document.id).limit(limit + 1)))
    return DocumentList(
        items=[view(session, doc) for doc in items[:limit]],
        next_cursor=items[limit - 1].id if len(items) > limit else None,
    )


@router.get("/documents/{document_id}", response_model=DocumentView)
def document(document_id: UUID, session: SessionDep, identity: IdentityDep):
    return view(session, service.get_document(session, identity, document_id))


@router.get("/documents/{document_id}/chunks", response_model=ChunkList)
def chunks(
    document_id: UUID,
    session: SessionDep,
    identity: IdentityDep,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
):
    doc = service.get_document(session, identity, document_id)
    if doc.status == "disabled":
        raise missing()
    items = list(
        session.scalars(
            select(DocumentChunk)
            .where(DocumentChunk.document_id == doc.id, DocumentChunk.generation == doc.generation)
            .order_by(DocumentChunk.ordinal)
            .offset(offset)
            .limit(limit + 1)
        )
    )
    return ChunkList(
        items=[ChunkView.model_validate(c) for c in items[:limit]],
        next_offset=offset + limit if len(items) > limit else None,
    )


@router.get("/documents/{document_id}/download")
def download(document_id: UUID, session: SessionDep, identity: IdentityDep):
    doc = service.get_document(session, identity, document_id)
    if doc.status == "disabled":
        raise missing()
    try:
        data = storage.read_original(doc.storage_key)
    except Exception:
        raise AppError(503, "STORAGE_UNAVAILABLE", "原文件暂时无法下载，请稍后重试。") from None
    return Response(
        data,
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(doc.title, safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/documents/{document_id}/reindex", response_model=JobView, status_code=202)
def reindex(document_id: UUID, session: SessionDep, identity: IdentityDep):
    doc = service.get_document(session, identity, document_id, write=True, lock=True)
    job = service.enqueue(session, identity, doc)
    session.commit()
    return job


@router.post("/documents/{document_id}/disable", response_model=DocumentView)
def disable(document_id: UUID, session: SessionDep, identity: IdentityDep):
    doc = service.get_document(session, identity, document_id, write=True, lock=True)
    service.stop_document(session, doc)
    return view(session, doc)


@router.delete("/documents/{document_id}")
def delete(document_id: UUID, session: SessionDep, identity: IdentityDep):
    doc = service.get_document(session, identity, document_id, write=True, lock=True)
    service.stop_document(session, doc, delete=True)
    return {"deleted": True}


def job_access(session, identity, job_id, write=False):
    job = session.get(Job, job_id)
    if job is None or job.organization_id != identity.organization_id:
        raise missing()
    doc = service.get_document(session, identity, job.resource_id, write=write, lock=write)
    session.refresh(job)
    return doc, job


@router.get("/jobs/{job_id}", response_model=JobView)
def job(job_id: UUID, session: SessionDep, identity: IdentityDep):
    return job_access(session, identity, job_id)[1]


@router.post("/jobs/{job_id}/retry", response_model=JobView, status_code=202)
def retry(job_id: UUID, session: SessionDep, identity: IdentityDep):
    doc, job = job_access(session, identity, job_id, write=True)
    if job.status not in {"failed", "cancelled"}:
        raise AppError(409, "JOB_NOT_RETRYABLE", "仅失败或取消的任务允许重试。")
    latest = service.latest_job(session, doc)
    if latest and latest.generation > job.generation:
        return latest
    result = service.enqueue(session, identity, doc)
    session.commit()
    return result


@router.post("/jobs/{job_id}/cancel", response_model=JobView)
def cancel(job_id: UUID, session: SessionDep, identity: IdentityDep):
    doc, job = job_access(session, identity, job_id, write=True)
    if job.status in {"queued", "running"}:
        job.status, job.lease_until = "cancelled", None
        doc.status = "parsed" if doc.generation else "failed"
        doc.error_code, doc.error_message = "CANCELLED", "处理已取消，可重试。"
        session.commit()
    return job
