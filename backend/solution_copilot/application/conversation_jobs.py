from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from solution_copilot.application.access import resolve_identity
from solution_copilot.application.conversations import (
    add_message,
    event,
    memory_rows,
    refresh_questions,
    run_access,
)
from solution_copilot.application.errors import AppError
from solution_copilot.application.requirements import merge, profile_for
from solution_copilot.domain.models import Clarification, GenerationRun, Message
from solution_copilot.infrastructure import database, generation


def checked_run(session, run_id):
    row = session.get(GenerationRun, run_id)
    if row is None:
        raise AppError(404, "NOT_FOUND", "运行不存在。")
    identity = resolve_identity(session, row.actor_user_id, row.organization_id)
    row, conversation, project = run_access(session, identity, run_id, True)
    if conversation.epoch != row.payload["epoch"]:
        raise AppError(409, "CONTEXT_RESET", "会话已经重置。")
    return row, conversation, project


def run_job(run_id):
    run_id = UUID(str(run_id))
    attempt = None
    try:
        with Session(database.get_engine()) as session:
            row, conversation, project = checked_run(session, run_id)
            if row.status != "queued":
                return
            if row.payload.get("kind") in {"verify", "export"}:
                from solution_copilot.application.deliveries import run_job as delivery_job

                session.rollback()
                delivery_job(run_id)
                return
            if row.payload.get("kind") == "solution":
                from solution_copilot.application.solution_jobs import run_job as solution_job

                session.rollback()
                solution_job(run_id)
                return
            row.status, row.attempts = "running", row.attempts + 1
            attempt = row.attempts
            row.lease_until = datetime.now(UTC) + timedelta(seconds=180)
            event(row, "run.started", attempt=attempt)
            event(row, "node.started", node="workflow" if row.workflow else "clarify")
            if row.payload.get("kind") == "workflow":
                from solution_copilot.application.workflows import advance

                advance(session, row, conversation, project)
                session.commit()
                return
            payload = row.payload
            # ponytail: last 20 messages / 20k chars; add rolling summaries if context grows.
            messages = list(
                session.scalars(
                    select(Message)
                    .where(
                        Message.conversation_id == conversation.id,
                        Message.epoch == conversation.epoch,
                    )
                    .order_by(Message.seq.desc())
                    .limit(20)
                )
            )
            context, size = [], 0
            for message in messages:
                text = "\n".join(b["text"] for b in message.content if b["type"] == "text")
                if size + len(text) > 20000:
                    break
                context.insert(0, dict(role=message.role, text=text))
                size += len(text)
            memories = [
                dict(id=str(m.id), version=m.version, content=m.content, scope=m.scope)
                for m in memory_rows(session, project)
                if m.status == "confirmed"
                and (m.scope != "conversation" or m.conversation_id == conversation.id)
            ]
            if sum(len(m["content"]) for m in memories) > 20000:
                raise AppError(422, "MEMORY_CONTEXT_LIMIT", "已确认记忆超过 20000 字，请先清理。")
            session.commit()
        output, info = generation.chat(payload, context, memories)
        with Session(database.get_engine()) as session:
            row, conversation, project = checked_run(session, run_id)
            if row.status != "running" or row.attempts != attempt:
                return
            current_memories = [
                dict(id=str(m.id), version=m.version, content=m.content, scope=m.scope)
                for m in memory_rows(session, project)
                if m.status == "confirmed"
                and (m.scope != "conversation" or m.conversation_id == conversation.id)
            ]
            if current_memories != memories:
                raise AppError(
                    409, "MEMORY_CHANGED", "运行期间记忆已修改，结果未写入，请重新发送。"
                )
            profile = profile_for(session, project, True)
            if profile.version != row.payload["base_version"]:
                raise AppError(
                    409, "PROFILE_CHANGED", "运行期间档案已修改，结果未写入，请重新发送。"
                )
            if output.items:
                merge(profile, output, [row.payload["source"]])
            refresh_questions(session, project, profile)
            citations = [
                {**s, "source_type": s["type"], "type": "citation"}
                for item in profile.items
                for s in item["sources"]
                if s["source_id"] == row.payload["source"]["source_id"]
            ]
            message = add_message(
                session,
                conversation,
                "assistant",
                [{"type": "text", "text": output.reply}, *citations],
                row.id,
                info,
            )
            # Durable deltas are replayable; provider JSON finishes before text is published.
            for offset in range(0, len(output.reply), 500):
                event(
                    row,
                    "message.delta",
                    message_id=str(message.id),
                    text=output.reply[offset : offset + 500],
                )
            for citation in citations:
                event(row, "citation.created", **citation)
            required = session.scalar(
                select(Clarification.id)
                .where(
                    Clarification.project_id == project.id,
                    Clarification.importance == "required",
                    Clarification.status == "open",
                )
                .limit(1)
            )
            row.status = "waiting_user" if required else "succeeded"
            row.model_info, row.lease_until = info, None
            event(
                row, "run.waiting_user" if required else "run.completed", message_id=str(message.id)
            )
            session.commit()
    except Exception as exc:
        with Session(database.get_engine()) as session:
            row = session.scalar(
                select(GenerationRun).where(GenerationRun.id == run_id).with_for_update()
            )
            if (
                row
                and row.status in {"queued", "running"}
                and (
                    attempt is None
                    or row.attempts == attempt
                    or (row.payload.get("kind") == "workflow" and row.attempts == attempt - 1)
                )
            ):
                row.status, row.lease_until = "failed", None
                row.error_message = (
                    exc.message if isinstance(exc, AppError) else "运行失败，结果未写入，请重试。"
                )
                event(row, "run.failed", message=row.error_message)
                session.commit()


def dispatch_once(send):
    now = datetime.now(UTC)
    with Session(database.get_engine()) as session:
        rows = session.scalars(
            select(GenerationRun)
            .where(
                or_(
                    GenerationRun.status == "queued",
                    and_(GenerationRun.status == "running", GenerationRun.lease_until < now),
                )
            )
            .with_for_update(skip_locked=True)
            .limit(100)
        ).all()
        for row in rows:
            if row.status == "running":
                if row.attempts >= 3:
                    row.status, row.lease_until = "failed", None
                    row.error_message = "处理进程多次中断，请重新发送。"
                    event(row, "run.failed", message=row.error_message)
                else:
                    row.status = "queued"
            if row.status == "queued" and (row.lease_until is None or row.lease_until <= now):
                try:
                    send(str(row.id))
                    row.lease_until = now + timedelta(seconds=30)
                except Exception:
                    pass
        session.commit()
