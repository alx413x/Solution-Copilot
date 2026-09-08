import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from solution_copilot.application.access import (
    customer_scope,
    get_customer,
    get_project,
    require_write,
)
from solution_copilot.application.errors import AppError, missing
from solution_copilot.application.parsing import PARAMETERS, validate_file
from solution_copilot.domain.models import Customer, Document, Job
from solution_copilot.infrastructure import documents as storage


def scope_access(session, identity, scope, customer_id, project_id, write=False):
    if scope not in {"organization", "customer", "project"}:
        raise AppError(422, "INVALID_SCOPE", "请选择组织、客户或项目作用域，暂不支持公共发布。")
    if scope == "organization":
        if customer_id or project_id:
            raise AppError(422, "INVALID_SCOPE", "组织资料不能指定客户或项目。")
    else:
        if customer_id is None or (scope == "project") != (project_id is not None):
            raise AppError(422, "INVALID_SCOPE", "请指定与作用域一致的客户和项目。")
        customer = get_customer(session, identity, customer_id)
        if write and customer.deleted_at:
            raise AppError(409, "ARCHIVED", "客户已归档，资料仅供查阅。")
        if project_id:
            project = get_project(session, identity, project_id)
            if project.customer_id != customer_id:
                raise missing()
            if write and project.status == "archived":
                raise AppError(409, "ARCHIVED", "项目已归档，资料仅供查阅。")
    if write:
        require_write(identity, owner_only=scope == "organization")


def document_scope(identity):
    return [
        Document.organization_id == identity.organization_id,
        Document.deleted_at.is_(None),
        or_(
            Document.scope == "organization",
            Document.customer_id.in_(select(Customer.id).where(*customer_scope(identity))),
        ),
    ]


def get_document(session, identity, document_id, write=False, lock=False):
    query = select(Document).where(Document.id == document_id, *document_scope(identity))
    if lock:
        query = query.with_for_update()
    document = session.scalar(query.execution_options(populate_existing=True))
    if document is None:
        raise missing()
    scope_access(
        session, identity, document.scope, document.customer_id, document.project_id, write
    )
    return document


def latest_job(session, document):
    return session.scalar(
        select(Job).where(Job.resource_id == document.id).order_by(Job.generation.desc()).limit(1)
    )


def enqueue(session, identity, document):
    current = latest_job(session, document)
    if current and current.status in {"queued", "running"}:
        return current
    if document.status == "disabled":
        raise AppError(409, "DOCUMENT_DISABLED", "资料已停用，请重新上传以恢复。")
    generation = (current.generation + 1) if current else 1
    job = Job(
        organization_id=document.organization_id,
        resource_id=document.id,
        actor_user_id=identity.user_id,
        generation=generation,
    )
    document.status = "uploaded"
    document.error_code = document.error_message = None
    session.add(job)
    session.flush()
    return job


def upload(session, identity, scope, customer_id, project_id, name, mime, data):
    scope_access(session, identity, scope, customer_id, project_id, write=True)
    extension, mime = validate_file(name, mime, data)
    title = name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not title or len(title) > 255 or any(ord(c) < 32 for c in title):
        raise AppError(422, "INVALID_FILENAME", "文件名无效。")
    digest = hashlib.sha256(data).hexdigest()
    query = (
        select(Document)
        .where(
            Document.organization_id == identity.organization_id,
            Document.sha256 == digest,
            Document.scope == scope,
            Document.customer_id == customer_id,
            Document.project_id == project_id,
        )
        .with_for_update()
    )
    document = session.scalar(query)
    if document and not document.deleted_at and document.status not in {"disabled", "failed"}:
        return document, latest_job(session, document), True
    if document:
        # Retain the tombstone ID; cleanup and revival serialize on the document lock.
        storage.put_original(document.storage_key, data, mime)
        document.deleted_at = None
        document.status = "uploaded"
        document.title = title
        document.data = {**document.data, "storage_ready": True, "storage_deleted": False}
        job = enqueue(session, identity, document)
        session.commit()
        return document, job, False
    document = Document(
        id=uuid4(),
        organization_id=identity.organization_id,
        customer_id=customer_id,
        project_id=project_id,
        scope=scope,
        title=title,
        mime_type=mime,
        sha256=digest,
        storage_key=f"{identity.organization_id}/originals/{uuid4().hex}{extension}",
        data={
            "extension": extension,
            "size_bytes": len(data),
            "storage_ready": False,
            "chunking": PARAMETERS,
        },
    )
    session.add(document)
    try:
        session.flush()
        job = enqueue(session, identity, document)
        # Persist intent first: a crash during S3 PUT can always be reconciled by the worker.
        session.commit()
    except IntegrityError:
        session.rollback()
        document = session.scalar(query)
        if document and not document.deleted_at:
            return document, latest_job(session, document), True
        raise AppError(409, "UPLOAD_CONFLICT", "同时上传发生冲突，请重试。") from None
    try:
        storage.put_original(document.storage_key, data, mime)
    except Exception:
        # Durable job owns bounded retries, including ambiguous successful PUT responses.
        return document, job, False
    document.data = {**document.data, "storage_ready": True}
    session.commit()
    return document, job, False


def stop_document(session, document, delete=False):
    document.status = "disabled"
    if delete:
        document.deleted_at = datetime.now(UTC)
    for job in session.scalars(
        select(Job).where(Job.resource_id == document.id, Job.status.in_(["queued", "running"]))
    ):
        job.status = "cancelled"
        job.lease_until = None
    session.commit()
