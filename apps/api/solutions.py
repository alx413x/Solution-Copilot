from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from fastapi import APIRouter, Query, Response
from solution_copilot.application import deliveries
from solution_copilot.application import solutions as service
from solution_copilot.application.conversation_schemas import RunView
from solution_copilot.application.delivery_schemas import DeliveryView, ExportInput, VerifyInput
from solution_copilot.application.requirements import project_access
from solution_copilot.application.solution_schemas import (
    ApproveOutline,
    CreateSolution,
    EditSection,
    GenerateInput,
    SolutionView,
    VersionInfo,
    VersionView,
)
from solution_copilot.domain.models import Solution
from sqlalchemy import select

from apps.api.auth import IdentityDep, SessionDep

router = APIRouter(prefix="/api/v1")


@router.get("/projects/{project_id}/solutions", response_model=SolutionView | None)
def latest(project_id: UUID, session: SessionDep, identity: IdentityDep):
    project_access(session, identity, project_id)
    row = session.scalar(select(Solution).where(Solution.project_id == project_id))
    return service.view(session, identity, row) if row else None


@router.post("/projects/{project_id}/solutions", response_model=SolutionView, status_code=201)
def create(project_id: UUID, data: CreateSolution, session: SessionDep, identity: IdentityDep):
    return service.view(session, identity, service.create(session, identity, project_id, data))


@router.get("/solutions/{solution_id}", response_model=SolutionView)
def get(solution_id: UUID, session: SessionDep, identity: IdentityDep):
    row, _ = service.access(session, identity, solution_id)
    return service.view(session, identity, row)


@router.post("/solutions/{solution_id}/outline", response_model=RunView, status_code=202)
def outline(solution_id: UUID, data: GenerateInput, session: SessionDep, identity: IdentityDep):
    return service.start(session, identity, solution_id, data, "outline")


@router.post("/solutions/{solution_id}/outline/approve", response_model=RunView, status_code=202)
def approve(solution_id: UUID, data: ApproveOutline, session: SessionDep, identity: IdentityDep):
    return service.start(session, identity, solution_id, data, "approve")


@router.post(
    "/solutions/{solution_id}/sections/{section_id}/generate",
    response_model=RunView,
    status_code=202,
)
def generate(
    solution_id: UUID,
    section_id: str,
    data: GenerateInput,
    session: SessionDep,
    identity: IdentityDep,
):
    return service.start(session, identity, solution_id, data, "section", section_id)


@router.patch("/solutions/{solution_id}", response_model=SolutionView)
def edit(solution_id: UUID, data: EditSection, session: SessionDep, identity: IdentityDep):
    return service.view(session, identity, service.edit(session, identity, solution_id, data))


@router.get("/solutions/{solution_id}/versions", response_model=list[VersionInfo])
def versions(
    solution_id: UUID,
    session: SessionDep,
    identity: IdentityDep,
    after: Annotated[int, Query(ge=0)] = 0,
):
    return service.versions(session, identity, solution_id, after)


@router.get("/solutions/{solution_id}/versions/{number}", response_model=VersionView)
def version(solution_id: UUID, number: int, session: SessionDep, identity: IdentityDep):
    return service.version(session, identity, solution_id, number)


@router.post("/solutions/{solution_id}/verify", response_model=DeliveryView, status_code=202)
def verify(solution_id: UUID, data: VerifyInput, session: SessionDep, identity: IdentityDep):
    return deliveries.view(deliveries.start(session, identity, solution_id, data, "verify"))


@router.post("/solutions/{solution_id}/exports", response_model=DeliveryView, status_code=202)
def export(solution_id: UUID, data: ExportInput, session: SessionDep, identity: IdentityDep):
    return deliveries.view(deliveries.start(session, identity, solution_id, data, "export"))


@router.get("/solutions/{solution_id}/deliveries", response_model=list[DeliveryView])
def deliveries_list(
    solution_id: UUID,
    session: SessionDep,
    identity: IdentityDep,
    version: Annotated[int, Query(ge=1, le=200)],
):
    return deliveries.listing(session, identity, solution_id, version)


@router.get("/exports/{export_id}/download")
def download(export_id: UUID, session: SessionDep, identity: IdentityDep):
    data, mime, name = deliveries.download(session, identity, export_id)
    return Response(
        data,
        media_type=mime,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
