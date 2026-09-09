from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from solution_copilot.application.access import resolve_identity
from solution_copilot.application.documents import get_document
from solution_copilot.application.errors import AppError
from solution_copilot.application.requirements import merge, profile_for, project_access
from solution_copilot.domain.models import RequirementExtraction
from solution_copilot.infrastructure import database, generation


def checked_job(session, job_id):
    row = session.get(RequirementExtraction, job_id)
    if row is None:
        raise AppError(404, "NOT_FOUND", "提取任务不存在。")
    identity = resolve_identity(session, row.actor_user_id, row.organization_id)
    project = project_access(session, identity, row.project_id, True)
    row = session.scalar(
        select(RequirementExtraction)
        .where(RequirementExtraction.id == job_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    for source in row.payload["sources"]:
        if source["type"] != "document":
            continue
        doc = get_document(session, identity, UUID(source["document_id"]))
        if doc.status == "disabled" or doc.generation != source["generation"]:
            raise AppError(409, "SOURCE_CHANGED", "来源已停用或重建，请重新提取。")
    return row, profile_for(session, project, True)


def run_job(job_id):
    job_id = UUID(str(job_id))
    attempt = None
    try:
        with Session(database.get_engine()) as session:
            row, profile = checked_job(session, job_id)
            if row.status != "queued":
                return
            row.status = "running"
            row.attempts += 1
            attempt = row.attempts
            row.lease_until = datetime.now(UTC) + timedelta(seconds=180)
            sources, existing = row.payload["sources"], row.payload["existing"]
            session.commit()
        output, info = generation.extract(sources, existing)
        with Session(database.get_engine()) as session:
            row, profile = checked_job(session, job_id)
            if row.status != "running" or row.attempts != attempt:
                return
            if profile.version != row.payload["base_version"]:
                raise AppError(
                    409, "PROFILE_CHANGED", "提取期间档案已修改，结果未写入，请重新提取。"
                )
            merge(profile, output, sources)
            row.model_info = info
            row.status, row.lease_until = "succeeded", None
            session.commit()
    except Exception as exc:
        with Session(database.get_engine()) as session:
            row = session.scalar(
                select(RequirementExtraction)
                .where(RequirementExtraction.id == job_id)
                .with_for_update()
            )
            if (
                row
                and row.status in {"queued", "running"}
                and (attempt is None or row.attempts == attempt)
            ):
                row.status, row.lease_until = "failed", None
                row.error_message = (
                    exc.message if isinstance(exc, AppError) else "提取失败，档案未修改，请重试。"
                )
                session.commit()


def dispatch_once(send):
    now = datetime.now(UTC)
    with Session(database.get_engine()) as session:
        rows = session.scalars(
            select(RequirementExtraction)
            .where(
                or_(
                    RequirementExtraction.status == "queued",
                    and_(
                        RequirementExtraction.status == "running",
                        RequirementExtraction.lease_until < now,
                    ),
                )
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for row in rows:
            if row.status == "running":
                if row.attempts >= 3:
                    row.status, row.lease_until = "failed", None
                    row.error_message = "处理进程多次中断，请重新提取。"
                else:
                    row.status = "queued"
            if row.status == "queued" and (row.lease_until is None or row.lease_until <= now):
                try:
                    send(str(row.id))
                    row.lease_until = now + timedelta(seconds=30)
                except Exception:
                    pass
        session.commit()
