"""Postgres jobs are also the durable outbox; Redis deliveries are only wake-up hints."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from solution_copilot.application.access import resolve_identity
from solution_copilot.application.documents import scope_access
from solution_copilot.application.errors import AppError
from solution_copilot.application.parsing import chunks, validate_file
from solution_copilot.config import get_settings
from solution_copilot.domain.models import Document, DocumentChunk, Job
from solution_copilot.infrastructure import database
from solution_copilot.infrastructure import documents as storage


class Cancelled(Exception):
    pass


def locked_pair(session, job_id):
    resource_id = session.scalar(select(Job.resource_id).where(Job.id == job_id))
    if resource_id is None:
        raise Cancelled()
    # Uniform lock order with API: document, then job.
    doc = session.scalar(select(Document).where(Document.id == resource_id).with_for_update())
    job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
    return doc, job


def authorize(session, doc, job):
    if doc.deleted_at or doc.status == "disabled":
        raise Cancelled()
    identity = resolve_identity(session, job.actor_user_id, job.organization_id)
    scope_access(session, identity, doc.scope, doc.customer_id, doc.project_id, write=True)


def fail(doc, job, error):
    job.status = "failed"
    job.error_code, job.error_message = error.code, error.message
    job.lease_until = None
    doc.status = "failed"
    doc.error_code, doc.error_message = error.code, error.message


def run_job(job_id):
    job_id = UUID(str(job_id))
    attempt = None
    try:
        with Session(database.get_engine()) as session:
            doc, job = locked_pair(session, job_id)
            if job.status != "queued":
                return
            try:
                authorize(session, doc, job)
            except AppError:
                fail(
                    doc,
                    job,
                    AppError(403, "ACCESS_REVOKED", "权限或档案状态已变更，请联系管理员。"),
                )
                session.commit()
                return
            job.attempts += 1
            attempt = job.attempts
            job.status, job.progress, doc.status = "running", 10, "parsing"
            job.lease_until = datetime.now(UTC) + timedelta(
                seconds=get_settings().job_lease_seconds
            )
            key, title, mime, digest = doc.storage_key, doc.title, doc.mime_type, doc.sha256
            session.commit()

        def checkpoint(progress=40):
            with Session(database.get_engine()) as session:
                doc, job = locked_pair(session, job_id)
                if job.status != "running" or job.attempts != attempt:
                    raise Cancelled()
                authorize(session, doc, job)
                job.progress = progress
                job.lease_until = datetime.now(UTC) + timedelta(
                    seconds=get_settings().job_lease_seconds
                )
                session.commit()

        data = storage.read_original(key)
        if hashlib.sha256(data).hexdigest() != digest:
            raise AppError(422, "CONTENT_CHANGED", "原文件校验失败，请删除后重新上传。")
        extension, _ = validate_file(title, mime, data)
        # Checkpoints between blocks, no persisted partial chunks.
        result = chunks(data, extension, checkpoint)
        checkpoint(80)
        with Session(database.get_engine()) as session:
            doc, job = locked_pair(session, job_id)
            if job.status != "running" or job.attempts != attempt:
                raise Cancelled()
            authorize(session, doc, job)
            session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
            session.add_all(
                [
                    DocumentChunk(
                        document_id=doc.id,
                        organization_id=doc.organization_id,
                        generation=job.generation,
                        **chunk,
                    )
                    for chunk in result
                ]
            )
            doc.generation, doc.status = job.generation, "parsed"
            doc.data = {**doc.data, "storage_ready": True, "chunk_count": len(result)}
            doc.error_code = doc.error_message = None
            job.status, job.progress, job.lease_until = "succeeded", 100, None
            job.error_code = job.error_message = None
            session.commit()
    except Cancelled:
        return
    except Exception as exc:
        with Session(database.get_engine()) as session:
            doc, job = locked_pair(session, job_id)
            if job.status != "running" or job.attempts != attempt:
                return
            if isinstance(exc, AppError):
                fail(doc, job, exc)
            elif job.attempts >= get_settings().job_max_attempts:
                fail(
                    doc,
                    job,
                    AppError(
                        422,
                        "PROCESSING_FAILED",
                        "处理失败。请检查文件是否损坏、原文件是否上传成功后重试或重新上传。",
                    ),
                )
            else:
                job.status, doc.status = "queued", "uploaded"
                job.lease_until = None
                job.dispatch_after = datetime.now(UTC) + timedelta(seconds=5 * job.attempts)
                job.error_code = "RETRY_PENDING"
                job.error_message = "服务或文件读取暂时失败，正在自动重试。"
            session.commit()


def dispatch_once(send):
    """Lease recovery, repeated enqueue, and durable deletion compensation."""
    now = datetime.now(UTC)
    with Session(database.get_engine()) as session:
        ids = list(
            session.scalars(
                select(Job.id)
                .where(
                    or_(
                        and_(Job.status == "queued", Job.dispatch_after <= now),
                        and_(Job.status == "running", Job.lease_until < now),
                    )
                )
                .order_by(Job.dispatch_after)
                .limit(100)
            )
        )
    for job_id in ids:
        with Session(database.get_engine()) as session:
            doc, job = locked_pair(session, job_id)
            if job.status == "running" and job.lease_until and job.lease_until < now:
                if job.attempts >= get_settings().job_max_attempts:
                    fail(doc, job, AppError(503, "WORKER_LOST", "处理进程多次中断，请重试。"))
                else:
                    job.status = "queued"
                    job.lease_until = None
            if job.status == "queued" and job.dispatch_after <= now:
                # Brief grace period for the HTTP process to finish initial object storage.
                if (
                    not doc.data.get("storage_ready")
                    and (now - doc.created_at).total_seconds() < 30
                ):
                    continue
                try:
                    send(str(job.id))
                    job.dispatch_after = now + timedelta(seconds=30)
                except Exception:
                    job.dispatch_after = now + timedelta(seconds=5)
            session.commit()
    with Session(database.get_engine()) as session:
        docs = session.scalars(
            select(Document)
            .where(Document.deleted_at.is_not(None))
            .with_for_update(skip_locked=True)
        ).all()
        for doc in docs:
            if doc.data.get("storage_deleted"):
                continue
            try:
                storage.delete_original(doc.storage_key)
            except Exception:
                continue
            session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == doc.id))
            doc.data = {**doc.data, "storage_deleted": True}
        session.commit()
