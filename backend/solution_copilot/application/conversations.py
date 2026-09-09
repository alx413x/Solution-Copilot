from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, or_, select

from solution_copilot.application.access import require_write
from solution_copilot.application.customers import active_customer, check_version, lock_customer
from solution_copilot.application.errors import AppError, missing
from solution_copilot.application.requirement_schemas import REQUIRED, Candidate, ExtractionOutput
from solution_copilot.application.requirements import merge, profile_for, project_access, view
from solution_copilot.domain.models import (
    AuditEvent,
    Clarification,
    Conversation,
    GenerationRun,
    Memory,
    Message,
)

QUESTIONS = {
    "background": "项目背景、当前业务流程和涉及人员是什么？",
    "pain_point": "当前最需要解决的具体困难是什么？",
    "goal": "本项目希望达成哪些业务目标？",
    "functional": "必须支持哪些功能或业务场景？",
    "integration": "需要对接哪些系统、接口或身份服务？没有对接需求也请说明。",
    "security_compliance": "有哪些权限、数据隔离和安全合规要求？",
    "constraint": "有哪些部署、预算、时间或资源限制？",
    "acceptance_metric": "以哪些可验证指标和方式验收？",
    "risk": "有哪些已知风险或需要提前验证的假设？",
}
TERMINAL = {"waiting_user", "succeeded", "failed", "cancelled"}


def conversation_access(session, identity, conversation_id, write=False):
    row = session.get(Conversation, conversation_id)
    if row is None or row.organization_id != identity.organization_id:
        raise missing()
    project = project_access(session, identity, row.project_id, write)
    session.refresh(row)
    return row, project


def run_access(session, identity, run_id, write=False):
    row = session.get(GenerationRun, run_id)
    if row is None or row.organization_id != identity.organization_id:
        raise missing()
    conversation, project = conversation_access(session, identity, row.conversation_id, write)
    session.refresh(row, with_for_update=write)
    return row, conversation, project


def event(run, kind, **data):
    run.events = [*run.events, {"id": len(run.events) + 1, "event": kind, "data": data}]


def audit(session, identity, action, resource_id, **data):
    session.add(
        AuditEvent(
            organization_id=identity.organization_id,
            actor_user_id=identity.user_id,
            action=action,
            resource_id=resource_id,
            data=data,
        )
    )


def create_conversation(session, identity, project_id, data):
    project_access(session, identity, project_id, True)
    if (
        session.scalar(
            select(func.count())
            .select_from(Conversation)
            .where(Conversation.project_id == project_id)
        )
        >= 100
    ):
        raise AppError(422, "CONVERSATION_LIMIT", "单项目最多 100 个会话，请复用已有会话。")
    row = Conversation(
        organization_id=identity.organization_id, project_id=project_id, title=data.title
    )
    session.add(row)
    session.commit()
    return row


def add_message(session, conversation, role, content, run_id=None, model_info=None):
    row = Message(
        id=uuid4(),
        organization_id=conversation.organization_id,
        conversation_id=conversation.id,
        epoch=conversation.epoch,
        seq=conversation.next_seq,
        role=role,
        content=content,
        run_id=run_id,
        model_info=model_info or {},
    )
    conversation.next_seq += 1
    session.add(row)
    session.flush()
    return row


def memory_rows(session, project):
    return list(
        session.scalars(
            select(Memory)
            .where(
                Memory.organization_id == project.organization_id,
                Memory.customer_id == project.customer_id,
                or_(Memory.scope == "customer", Memory.project_id == project.id),
                Memory.status != "expired",
                or_(Memory.expires_at.is_(None), Memory.expires_at > datetime.now(UTC)),
            )
            .order_by(Memory.created_at, Memory.id)
        )
    )


def workspace(session, identity, project_id):
    project = project_access(session, identity, project_id)
    return dict(
        conversations=list(
            session.scalars(
                select(Conversation)
                .where(Conversation.project_id == project_id)
                .order_by(Conversation.created_at)
            )
        ),
        clarifications=list(
            session.scalars(
                select(Clarification)
                .where(Clarification.project_id == project_id)
                .order_by(Clarification.created_at)
            )
        ),
        memories=memory_rows(session, project),
        writable=view(session, identity, project_id)["writable"],
    )


def refresh_questions(session, project, profile):
    present = {i["category"] for i in profile.items if i["status"] in {"proposed", "confirmed"}}
    questions = list(
        session.scalars(select(Clarification).where(Clarification.project_id == project.id))
    )
    existing = {q.category for q in questions}
    for question in questions:
        if question.status == "open" and question.category in present:
            item = next(
                i
                for i in profile.items
                if i["category"] == question.category and i["status"] in {"proposed", "confirmed"}
            )
            question.status, question.answer = "answered", item["content"]
            source = next((s for s in item["sources"] if s.get("message_id")), None)
            question.source_message_id = source["message_id"] if source else None
            question.answered_at = datetime.now(UTC)
            question.version += 1
        elif question.status == "answered" and question.category not in present:
            question.status = "open"
            question.version += 1
    for category, question in QUESTIONS.items():
        if category not in present and category not in existing:
            session.add(
                Clarification(
                    organization_id=project.organization_id,
                    project_id=project.id,
                    category=category,
                    question=question,
                    reason="需求档案尚缺少此类信息。",
                    importance="required" if category in REQUIRED else "recommended",
                )
            )
    session.flush()


def generate_questions(session, identity, project_id):
    project = project_access(session, identity, project_id, True)
    refresh_questions(session, project, profile_for(session, project, True))
    session.commit()
    return workspace(session, identity, project_id)["clarifications"]


def question_access(session, identity, question_id):
    row = session.get(Clarification, question_id)
    if row is None or row.organization_id != identity.organization_id:
        raise missing()
    project = project_access(session, identity, row.project_id, True)
    session.refresh(row)
    return row, project


def answer(session, identity, question_id, data):
    question, project = question_access(session, identity, question_id)
    check_version(question, data.version)
    conversation, _ = conversation_access(session, identity, data.conversation_id)
    if conversation.project_id != project.id:
        raise missing()
    if conversation.epoch != data.epoch:
        raise AppError(409, "CONTEXT_RESET", "会话已重置，请刷新后重新回答。")
    profile = profile_for(session, project, True)
    check_version(profile, data.profile_version)
    message = add_message(
        session,
        conversation,
        "user",
        [
            {"type": "text", "text": data.answer},
            {
                "type": "tool_status",
                "clarification_id": str(question.id),
                "question": question.question,
            },
        ],
    )
    source = message_source(message, data.answer)
    # Explicit category answer is already structured; no model call is needed.
    merge(
        profile,
        ExtractionOutput(
            summary=profile.summary,
            items=[
                Candidate(
                    category=question.category,
                    title=question.question,
                    content=data.answer,
                    priority="unknown",
                    confidence=1,
                    source_id=str(message.id),
                    quote=data.answer,
                )
            ],
        ),
        [source],
    )
    for item in profile.items:
        if any(s["source_id"] == str(message.id) for s in item["sources"]):
            item["confidence"] = None
    question.answer, question.status = data.answer, "answered"
    question.source_message_id, question.answered_by = message.id, identity.user_id
    question.answered_at = datetime.now(UTC)
    question.version += 1
    session.commit()
    return question


def skip(session, identity, question_id, data):
    row, _ = question_access(session, identity, question_id)
    check_version(row, data.version)
    if row.importance != "recommended" or row.status != "open":
        raise AppError(409, "REQUIRED_QUESTION", "只能跳过尚未回答的建议问题。")
    row.status, row.version = "skipped", row.version + 1
    session.commit()
    return row


def message_source(message, text):
    return dict(
        source_id=str(message.id),
        type="message",
        title="对话消息",
        message_id=str(message.id),
        conversation_id=str(message.conversation_id),
        message_seq=message.seq,
        content=text,
    )


def history(session, identity, conversation_id, after=0):
    conversation, _ = conversation_access(session, identity, conversation_id)
    rows = list(
        session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.seq > after)
            .order_by(Message.seq)
            .limit(101)
        )
    )
    return dict(
        conversation=conversation,
        messages=rows[:100],
        next_after=rows[99].seq if len(rows) > 100 else None,
        run=session.scalar(
            select(GenerationRun)
            .where(GenerationRun.conversation_id == conversation_id)
            .order_by(GenerationRun.created_at.desc())
            .limit(1)
        ),
    )


def send_message(session, identity, conversation_id, data):
    conversation, project = conversation_access(session, identity, conversation_id, True)
    prior = session.scalar(
        select(GenerationRun).where(
            GenerationRun.conversation_id == conversation_id,
            GenerationRun.request_id == data.request_id,
        )
    )
    if prior:
        if prior.payload.get("text") != data.text or prior.payload["epoch"] != data.epoch:
            raise AppError(409, "REQUEST_REUSED", "请求标识已用于其他消息。")
        return prior
    if conversation.epoch != data.epoch:
        raise AppError(409, "CONTEXT_RESET", "会话已重置，请刷新后重新发送。")
    if session.scalar(
        select(GenerationRun).where(
            GenerationRun.project_id == project.id, GenerationRun.status.in_(["queued", "running"])
        )
    ):
        raise AppError(409, "RUN_ACTIVE", "此项目已有运行，请等待完成或取消。")
    message = add_message(session, conversation, "user", [{"type": "text", "text": data.text}])
    profile = profile_for(session, project, True)
    existing = [
        {k: i[k] for k in ("id", "category", "title", "content", "priority", "status")}
        for i in profile.items
    ]
    if sum(len(i["content"]) + len(i["title"]) for i in existing) > 30000:
        raise AppError(422, "PROFILE_LIMIT", "档案超过单次模型输入上限。")
    row = GenerationRun(
        organization_id=identity.organization_id,
        project_id=project.id,
        conversation_id=conversation.id,
        actor_user_id=identity.user_id,
        request_id=data.request_id,
        events=[],
        payload=dict(
            text=data.text,
            epoch=conversation.epoch,
            base_version=profile.version,
            existing=existing,
            source=message_source(message, data.text),
        ),
    )
    session.add(row)
    session.flush()
    message.run_id = row.id
    session.commit()
    return row


def cancel_run(session, identity, run_id):
    row, _, _ = run_access(session, identity, run_id, True)
    if row.status in {"queued", "running", "waiting_user"}:
        row.status, row.lease_until = "cancelled", None
        event(row, "run.cancelled")
    session.commit()
    return row


def create_memory(session, identity, project_id, data):
    project = project_access(session, identity, project_id, True)
    message = session.get(Message, data.source_message_id)
    if message is None:
        raise missing()
    conversation, _ = conversation_access(session, identity, message.conversation_id)
    if conversation.project_id != project.id:
        raise missing()
    # ponytail: bounded customer memory collection; add pagination above 200 active records.
    if (
        session.scalar(
            select(func.count())
            .select_from(Memory)
            .where(Memory.customer_id == project.customer_id, Memory.status != "expired")
        )
        >= 200
    ):
        raise AppError(422, "MEMORY_LIMIT", "客户最多保存 200 条活动记忆，请先清理。")
    row = Memory(
        organization_id=identity.organization_id,
        customer_id=project.customer_id,
        project_id=project.id if data.scope != "customer" else None,
        conversation_id=conversation.id if data.scope == "conversation" else None,
        scope=data.scope,
        kind=data.kind,
        content=data.content,
        source_message_id=message.id,
    )
    session.add(row)
    session.flush()
    audit(session, identity, "memory.created", row.id, scope=row.scope)
    session.commit()
    return row


def memory_access(session, identity, memory_id):
    row = session.get(Memory, memory_id)
    if row is None or row.organization_id != identity.organization_id:
        raise missing()
    require_write(identity)
    customer = lock_customer(session, identity, row.customer_id)
    active_customer(customer)
    if row.project_id:
        project_access(session, identity, row.project_id, True)
    session.refresh(row)
    return row


def edit_memory(session, identity, memory_id, data):
    row = memory_access(session, identity, memory_id)
    check_version(row, data.version)
    if data.expires_at and data.expires_at.tzinfo is None:
        raise AppError(422, "TIMEZONE_REQUIRED", "到期时间必须包含时区。")
    row.content, row.status, row.expires_at = data.content, data.status, data.expires_at
    row.version += 1
    audit(session, identity, "memory.updated", row.id, status=row.status, version=row.version)
    session.commit()
    return row


def delete_memory(session, identity, memory_id, version):
    row = memory_access(session, identity, memory_id)
    check_version(row, version)
    audit(session, identity, "memory.deleted", row.id, scope=row.scope)
    session.delete(row)
    session.commit()
    return {"deleted": True}


def reset(session, identity, resource_id, confirm, scope):
    conversation = None
    if scope == "conversation":
        conversation, project = conversation_access(session, identity, resource_id, True)
        filters = [Memory.conversation_id == resource_id]
    else:
        project = project_access(session, identity, resource_id, True)
        filters = [Memory.project_id == resource_id, Memory.scope == "project"]
    memories = list(session.scalars(select(Memory).where(*filters, Memory.status != "expired")))
    runs = list(
        session.scalars(
            select(GenerationRun).where(
                GenerationRun.project_id == project.id,
                GenerationRun.status.in_(["queued", "running", "waiting_user"]),
                *([GenerationRun.conversation_id == resource_id] if conversation else []),
            )
        )
    )
    count = (
        session.scalar(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == resource_id, Message.epoch == conversation.epoch)
        )
        if conversation
        else 0
    )
    result = dict(confirmed=confirm, memories=len(memories), context_messages=count, runs=len(runs))
    if confirm:
        for memory in memories:
            memory.status, memory.version = "expired", memory.version + 1
        for run in runs:
            run.status, run.lease_until = "cancelled", None
            event(run, "run.cancelled", reason="context_reset")
        if conversation:
            conversation.epoch += 1
        audit(session, identity, scope + ".reset", resource_id, **result)
        session.commit()
    return result
