from uuid import UUID

from fastapi import APIRouter
from solution_copilot.application import requirements as service
from solution_copilot.application.requirement_schemas import (
    ConfirmInput,
    EditInput,
    ExtractionInput,
    ExtractionView,
    ProfileView,
)

from apps.api.auth import IdentityDep, SessionDep

router = APIRouter(prefix="/api/v1/projects/{project_id}/requirements")


@router.get("", response_model=ProfileView)
def profile(project_id: UUID, session: SessionDep, identity: IdentityDep):
    return service.view(session, identity, project_id)


@router.patch("", response_model=ProfileView)
def edit(project_id: UUID, data: EditInput, session: SessionDep, identity: IdentityDep):
    return service.edit(session, identity, project_id, data)


@router.post("/confirm", response_model=ProfileView)
def confirm(project_id: UUID, data: ConfirmInput, session: SessionDep, identity: IdentityDep):
    return service.edit(session, identity, project_id, data, confirm=True)


@router.post("/extractions", response_model=ExtractionView, status_code=202)
def extract(project_id: UUID, data: ExtractionInput, session: SessionDep, identity: IdentityDep):
    return service.start(session, identity, project_id, data)


@router.post("/extractions/{extraction_id}/cancel", response_model=ExtractionView)
def cancel(project_id: UUID, extraction_id: UUID, session: SessionDep, identity: IdentityDep):
    return service.cancel(session, identity, project_id, extraction_id)
