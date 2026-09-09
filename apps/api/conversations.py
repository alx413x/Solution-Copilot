import json
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials
from solution_copilot.application import conversations as service
from solution_copilot.application.access import resolve_identity
from solution_copilot.application.conversation_schemas import (
    AnswerInput,
    ClarificationView,
    ConversationInput,
    ConversationView,
    HistoryView,
    MemoryEdit,
    MemoryInput,
    MemoryView,
    MessageInput,
    MessageView,
    ResetInput,
    RunView,
    VersionInput,
    WorkspaceView,
)
from solution_copilot.application.errors import AppError
from solution_copilot.infrastructure import database
from sqlalchemy.orm import Session

from apps.api.auth import IdentityDep, SessionDep, authenticate

router = APIRouter(prefix="/api/v1")


@router.get("/projects/{project_id}/dialogue", response_model=WorkspaceView)
def workspace(project_id: UUID, session: SessionDep, identity: IdentityDep):
    return service.workspace(session, identity, project_id)


@router.post(
    "/projects/{project_id}/conversations", response_model=ConversationView, status_code=201
)
def create(project_id: UUID, data: ConversationInput, session: SessionDep, identity: IdentityDep):
    return service.create_conversation(session, identity, project_id, data)


@router.get("/conversations/{conversation_id}/messages", response_model=HistoryView)
def history(
    conversation_id: UUID,
    session: SessionDep,
    identity: IdentityDep,
    after: Annotated[int, Query(ge=0)] = 0,
):
    return service.history(session, identity, conversation_id, after)


@router.post("/conversations/{conversation_id}/messages", response_model=RunView, status_code=202)
def send(conversation_id: UUID, data: MessageInput, session: SessionDep, identity: IdentityDep):
    return service.send_message(session, identity, conversation_id, data)


@router.get("/projects/{project_id}/clarifications", response_model=list[ClarificationView])
def questions(project_id: UUID, session: SessionDep, identity: IdentityDep):
    return service.workspace(session, identity, project_id)["clarifications"]


@router.post("/projects/{project_id}/clarifications", response_model=list[ClarificationView])
def generate(project_id: UUID, session: SessionDep, identity: IdentityDep):
    return service.generate_questions(session, identity, project_id)


@router.post("/clarifications/{question_id}/answer", response_model=ClarificationView)
def answer(question_id: UUID, data: AnswerInput, session: SessionDep, identity: IdentityDep):
    return service.answer(session, identity, question_id, data)


@router.post("/clarifications/{question_id}/skip", response_model=ClarificationView)
def skip(question_id: UUID, data: VersionInput, session: SessionDep, identity: IdentityDep):
    return service.skip(session, identity, question_id, data)


@router.get("/runs/{run_id}", response_model=RunView)
def run(run_id: UUID, session: SessionDep, identity: IdentityDep):
    return service.run_access(session, identity, run_id)[0]


@router.post("/runs/{run_id}/cancel", response_model=RunView)
def cancel(run_id: UUID, session: SessionDep, identity: IdentityDep):
    return service.cancel_run(session, identity, run_id)


@router.post("/runs/{run_id}/resume", response_model=RunView, status_code=202)
def resume(run_id: UUID, data: MessageInput, session: SessionDep, identity: IdentityDep):
    row, conversation, _ = service.run_access(session, identity, run_id, True)
    if row.status != "waiting_user":
        raise AppError(409, "NOT_WAITING", "此运行不在等待输入状态。")
    # S05 follow-up is a new idempotent run. Graph checkpoint resume belongs to S06.
    return service.send_message(session, identity, conversation.id, data)


def stream_events(run_id, identity, credential, after):
    # Short-lived DB sessions: no connection/transaction is held while waiting for the worker.
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        try:
            with Session(database.get_engine()) as session:
                user = authenticate(session, credential)
                current = resolve_identity(session, user.id, identity.organization_id)
                row, _, _ = service.run_access(session, current, run_id)
                events, terminal = row.events, row.status in service.TERMINAL
            for entry in events:
                if entry["id"] > after:
                    data = json.dumps(entry["data"], ensure_ascii=False)
                    yield f"id: {entry['id']}\nevent: {entry['event']}\ndata: {data}\n\n"
                    after = entry["id"]
            if terminal:
                yield "event: stream.end\ndata: {}\n\n"
                return
            yield ": heartbeat\n\n"
        except AppError:
            yield "event: stream.denied\ndata: {}\n\n"
            return
        time.sleep(1)


@router.get("/runs/{run_id}/events")
def events(
    run_id: UUID,
    session: SessionDep,
    identity: IdentityDep,
    authorization: Annotated[str, Header()],
    last_event_id: Annotated[str | None, Header()] = None,
    after: Annotated[int, Query(ge=0)] = 0,
):
    row, _, _ = service.run_access(session, identity, run_id)
    try:
        cursor = int(last_event_id) if last_event_id is not None else after
    except ValueError:
        raise AppError(422, "INVALID_CURSOR", "事件游标必须是非负整数。") from None
    if cursor < 0 or cursor > len(row.events):
        raise AppError(422, "INVALID_CURSOR", "事件游标超出此运行范围。")
    credential = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=authorization.split(" ", 1)[1]
    )
    session.rollback()  # Release the request connection before the long-lived stream.
    return StreamingResponse(
        stream_events(run_id, identity, credential, cursor),
        media_type="text/event-stream",
        headers={"Cache-Control": "private, no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/projects/{project_id}/memories", response_model=list[MemoryView])
def memories(project_id: UUID, session: SessionDep, identity: IdentityDep):
    return service.workspace(session, identity, project_id)["memories"]


@router.post("/projects/{project_id}/memories", response_model=MemoryView, status_code=201)
def create_memory(project_id: UUID, data: MemoryInput, session: SessionDep, identity: IdentityDep):
    return service.create_memory(session, identity, project_id, data)


@router.patch("/memories/{memory_id}", response_model=MemoryView)
def edit_memory(memory_id: UUID, data: MemoryEdit, session: SessionDep, identity: IdentityDep):
    return service.edit_memory(session, identity, memory_id, data)


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: UUID, data: VersionInput, session: SessionDep, identity: IdentityDep):
    return service.delete_memory(session, identity, memory_id, data.version)


@router.post("/conversations/{conversation_id}/reset")
def reset_conversation(
    conversation_id: UUID, data: ResetInput, session: SessionDep, identity: IdentityDep
):
    return service.reset(session, identity, conversation_id, data.confirm, "conversation")


@router.post("/projects/{project_id}/memories/reset")
def reset_project(project_id: UUID, data: ResetInput, session: SessionDep, identity: IdentityDep):
    return service.reset(session, identity, project_id, data.confirm, "project")


@router.get("/messages/{message_id}", response_model=MessageView)
def source_message(message_id: UUID, session: SessionDep, identity: IdentityDep):
    from solution_copilot.application.errors import missing
    from solution_copilot.domain.models import Message

    message = session.get(Message, message_id)
    if message is None:
        raise missing()
    service.conversation_access(session, identity, message.conversation_id)
    return message
