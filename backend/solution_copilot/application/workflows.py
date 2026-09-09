"""S06: two durable human gates; S07 owns actual section generation."""

from typing import TypedDict
from uuid import UUID, uuid4

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import Field
from sqlalchemy import select

from solution_copilot.application import retrieval
from solution_copilot.application.access import resolve_identity
from solution_copilot.application.conversations import (
    add_message,
    audit,
    conversation_access,
    event,
    refresh_questions,
    run_access,
)
from solution_copilot.application.documents import document_scope
from solution_copilot.application.errors import AppError
from solution_copilot.application.requirement_schemas import REQUIRED
from solution_copilot.application.requirements import profile_for
from solution_copilot.application.schemas import Input
from solution_copilot.domain.models import Document, DocumentChunk, GenerationRun
from solution_copilot.infrastructure import embeddings

OUTLINE = [
    "执行摘要",
    "客户背景与现状",
    "需求与痛点分析",
    "建设目标",
    "总体解决方案",
    "功能设计",
    "技术架构",
    "系统集成与数据流",
    "安全与合规",
    "实施计划",
    "风险及应对措施",
    "验收指标",
    "预期价值",
    "参考资料",
]


class WorkflowInput(Input):
    goal: str = Field(min_length=1, max_length=500)
    request_id: UUID
    epoch: int = Field(ge=0)


class WorkflowResume(Input):
    request_id: UUID
    gate: int = Field(ge=1, le=2)
    approve: bool


class State(TypedDict, total=False):
    organization_id: str
    customer_id: str
    project_id: str
    conversation_id: str
    run_id: str
    user_goal: str
    requirement_profile_id: str
    profile_version: int
    ready: bool
    evidence: list[dict]
    outline: list[dict]
    warnings: list[str]


def graph(saver):
    def requirements(state):
        if not state["ready"]:
            return interrupt({"gate": 1, "stage": "requirements"})
        return {}

    def outline(state):
        return {"outline": [dict(id=f"section-{i:02}", title=t) for i, t in enumerate(OUTLINE, 1)]}

    def approval(state):
        interrupt({"gate": 2, "stage": "outline"})
        return {}

    builder = StateGraph(State)
    builder.add_node("validate_requirements", requirements)
    builder.add_node("draft_outline", outline)
    builder.add_node("wait_outline_approval", approval)
    builder.add_edge(START, "validate_requirements")
    builder.add_edge("validate_requirements", "draft_outline")
    builder.add_edge("draft_outline", "wait_outline_approval")
    builder.add_edge("wait_outline_approval", END)
    return builder.compile(checkpointer=saver)


def active_check(session, project_id, exclude=None, workflow_only=False):
    query = select(GenerationRun.id).where(GenerationRun.project_id == project_id)
    if workflow_only:
        query = query.where(
            GenerationRun.payload["kind"].astext == "workflow",
            GenerationRun.status.in_(["queued", "running", "waiting_user"]),
        )
    else:
        query = query.where(GenerationRun.status.in_(["queued", "running"]))
    if exclude:
        query = query.where(GenerationRun.id != exclude)
    if session.scalar(query.limit(1)):
        raise AppError(409, "RUN_ACTIVE", "项目已有运行，请先完成或取消。")


def start(session, identity, conversation_id, data):
    conversation, project = conversation_access(session, identity, conversation_id, True)
    original = data.model_dump(mode="json")
    prior = session.scalar(
        select(GenerationRun).where(
            GenerationRun.conversation_id == conversation_id,
            GenerationRun.request_id == data.request_id,
        )
    )
    if prior:
        if prior.payload.get("start") != original:
            raise AppError(409, "REQUEST_CONFLICT", "请求编号已用于不同内容。")
        return prior
    if data.epoch != conversation.epoch or not data.goal.strip():
        raise AppError(409, "CONTEXT_RESET", "会话已重置或目标为空，请刷新。")
    active_check(session, project.id)
    active_check(session, project.id, workflow_only=True)
    row = GenerationRun(
        id=uuid4(),
        organization_id=project.organization_id,
        project_id=project.id,
        conversation_id=conversation.id,
        actor_user_id=identity.user_id,
        request_id=data.request_id,
        payload={
            "kind": "workflow",
            "epoch": conversation.epoch,
            "start": original,
            "workflow": {"stage": "queued", "gate": 0, "outline": [], "warnings": []},
            "resumes": {},
        },
        events=[],
    )
    session.add(row)
    audit(session, identity, "workflow.start", row.id)
    session.commit()
    return row


def latest(session, identity, conversation_id):
    conversation_access(session, identity, conversation_id)
    return session.scalar(
        select(GenerationRun)
        .where(
            GenerationRun.conversation_id == conversation_id,
            GenerationRun.payload["kind"].astext == "workflow",
        )
        .order_by(GenerationRun.created_at.desc())
        .limit(1)
    )


def ready_profile(session, project):
    profile = profile_for(session, project, True)
    present = {i["category"] for i in profile.items if i["status"] == "confirmed"}
    ready = (
        bool(profile.confirmed_at)
        and set(REQUIRED) <= present
        and not any(i["status"] == "conflicted" for i in profile.items)
    )
    return profile, ready


def resume(session, identity, run_id, data):
    row, conversation, project = run_access(session, identity, run_id, True)
    if row.payload.get("kind") != "workflow":
        raise AppError(409, "NOT_WORKFLOW", "此运行不是编排任务。")
    original = data.model_dump(mode="json")
    prior = row.payload["resumes"].get(str(data.request_id))
    if prior:
        if prior != original:
            raise AppError(409, "REQUEST_CONFLICT", "请求编号已用于不同确认。")
        return row
    if not data.approve or row.status != "waiting_user" or row.workflow["gate"] != data.gate:
        raise AppError(409, "STALE_GATE", "确认点已变更；拒绝大纲时请取消运行。")
    if conversation.epoch != row.payload["epoch"]:
        raise AppError(409, "CONTEXT_RESET", "会话已重置。")
    profile, ready = ready_profile(session, project)
    if not ready:
        raise AppError(409, "REQUIREMENTS_UNCONFIRMED", "请补齐八类需求、解决冲突并确认需求档案。")
    if data.gate == 2:
        validate_snapshot(session, identity, project, row.payload["snapshot"], profile)
    active_check(session, project.id, row.id)
    row.payload = {
        **row.payload,
        "resume_gate": data.gate,
        "approved_profile_version": profile.version,
        "resumes": {**row.payload["resumes"], str(data.request_id): original},
    }
    row.actor_user_id = identity.user_id
    row.status, row.lease_until = "queued", None
    audit(session, identity, "workflow.resume", row.id, gate=data.gate)
    session.commit()
    return row


def validate_snapshot(session, identity, project, snapshot, profile):
    if not profile.confirmed_at or profile.version != snapshot["profile_version"]:
        raise AppError(409, "PROFILE_CHANGED", "需求档案已变更，请取消并重新开始编排。")
    for reference in snapshot["evidence"]:
        chunk = session.scalar(
            select(DocumentChunk)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(
                DocumentChunk.id == UUID(reference["chunk_id"]),
                *document_scope(identity),
                Document.status != "disabled",
                DocumentChunk.generation == Document.generation,
                DocumentChunk.generation == reference["generation"],
                DocumentChunk.embedding_profile == embeddings.PROFILE,
            )
            .with_for_update(of=Document)
        )
        doc = session.get(Document, chunk.document_id) if chunk else None
        if (
            doc is None
            or (doc.scope == "customer" and doc.customer_id != project.customer_id)
            or (doc.scope == "project" and doc.project_id != project.id)
        ):
            raise AppError(409, "EVIDENCE_CHANGED", "引用资料已失效，请取消并重新检索。")


def advance(session, row, conversation, project):
    """Caller holds the project/run locks. Checkpoints and publication commit together."""
    identity = resolve_identity(session, row.actor_user_id, row.organization_id)
    profile, ready = ready_profile(session, project)
    gate = row.payload.get("resume_gate")
    if gate and (not ready or profile.version != row.payload["approved_profile_version"]):
        raise AppError(409, "REQUIREMENTS_UNCONFIRMED", "需求已变更，请重新确认。")
    if gate == 2:
        snapshot = row.payload["snapshot"]
        validate_snapshot(session, identity, project, snapshot, profile)
    else:
        refresh_questions(session, project, profile)
        hits = (
            retrieval.search(
                session,
                identity,
                retrieval.SearchInput(query=row.payload["start"]["goal"], project_id=project.id),
            )["items"]
            if ready
            else []
        )
        snapshot = dict(
            requirement_profile_id=str(profile.id),
            profile_version=profile.version,
            ready=ready,
            evidence=[
                dict(chunk_id=str(hit["chunk_id"]), generation=hit["generation"]) for hit in hits
            ],
            warnings=[] if hits else ["暂无检索证据；大纲仅为固定章节模板。"],
        )
    session.flush()
    # Native saver uses the existing transaction; sync durability finishes writes before commit.
    saver = PostgresSaver(session.connection().connection.driver_connection)
    workflow = graph(saver)
    config = {"configurable": {"thread_id": str(row.id)}}
    initial = dict(
        organization_id=str(project.organization_id),
        customer_id=str(project.customer_id),
        project_id=str(project.id),
        conversation_id=str(conversation.id),
        run_id=str(row.id),
        user_goal=row.payload["start"]["goal"],
        **snapshot,
    )
    result = workflow.invoke(
        Command(resume=snapshot if gate == 1 else True) if gate else initial,
        config,
        durability="sync",
    )
    pauses = result.get("__interrupt__", [])
    view = dict(
        stage="ready_for_generation",
        gate=0,
        outline=result.get("outline", []),
        warnings=result.get("warnings", []),
    )
    if pauses:
        view.update(pauses[0].value)
    row.payload = {**row.payload, "snapshot": snapshot, "workflow": view}
    row.status, row.lease_until = ("waiting_user" if pauses else "succeeded"), None
    event(row, "node.completed", node=view["stage"])
    if not pauses:
        message = add_message(
            session,
            conversation,
            "assistant",
            [
                {
                    "type": "text",
                    "text": "大纲已确认。S06 编排完成；正文生成将在 S07 接入。\n"
                    + "\n".join(s["title"] for s in view["outline"]),
                }
            ],
            row.id,
        )
        event(row, "message.delta", message_id=str(message.id), text=message.content[0]["text"])
    event(row, "run.waiting_user" if pauses else "run.completed", **view)
