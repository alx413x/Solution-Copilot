from uuid import UUID

from fastapi import APIRouter, Query
from solution_copilot.application import customers as service
from solution_copilot.application.access import get_customer, get_project
from solution_copilot.application.schemas import (
    CustomerCreate,
    CustomerOut,
    CustomerPage,
    CustomerUpdate,
    ProjectCreate,
    ProjectOut,
    ProjectPage,
    ProjectUpdate,
    VersionInput,
)
from solution_copilot.domain.models import Membership, Organization
from sqlalchemy import select

from apps.api.auth import IdentityDep, SessionDep, UserDep

router = APIRouter(prefix="/api/v1")


@router.get("/me")
def me(session: SessionDep, user: UserDep):
    rows = session.execute(
        select(Organization, Membership.role)
        .join(Membership, Organization.id == Membership.organization_id)
        .where(Membership.user_id == user.id)
    ).all()
    return {
        "user": {"id": user.id, "display_name": user.display_name},
        "organizations": [{"id": org.id, "name": org.name, "role": role} for org, role in rows],
    }


@router.get("/customers", response_model=CustomerPage)
def customers(
    session: SessionDep,
    identity: IdentityDep,
    limit: int = Query(20, ge=1, le=100),
    after: UUID | None = None,
    archived: bool = False,
):
    return service.list_customers(session, identity, limit, after, archived)


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(data: CustomerCreate, session: SessionDep, identity: IdentityDep):
    return service.create_customer(session, identity, data)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def customer(customer_id: UUID, session: SessionDep, identity: IdentityDep):
    return get_customer(session, identity, customer_id)


@router.patch("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: UUID, data: CustomerUpdate, session: SessionDep, identity: IdentityDep
):
    return service.update_customer(session, identity, customer_id, data)


@router.delete("/customers/{customer_id}", response_model=CustomerOut)
def archive_customer(
    customer_id: UUID, data: VersionInput, session: SessionDep, identity: IdentityDep
):
    return service.archive_customer(session, identity, customer_id, data.version)


@router.post("/customers/{customer_id}/projects", response_model=ProjectOut, status_code=201)
def create_project(
    customer_id: UUID, data: ProjectCreate, session: SessionDep, identity: IdentityDep
):
    return service.create_project(session, identity, customer_id, data)


@router.get("/projects", response_model=ProjectPage)
def projects(
    session: SessionDep,
    identity: IdentityDep,
    limit: int = Query(20, ge=1, le=100),
    after: UUID | None = None,
    archived: bool = False,
    customer_id: UUID | None = None,
):
    return service.list_projects(session, identity, limit, after, archived, customer_id)


@router.get("/projects/{project_id}", response_model=ProjectOut)
def project(project_id: UUID, session: SessionDep, identity: IdentityDep):
    return get_project(session, identity, project_id)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: UUID, data: ProjectUpdate, session: SessionDep, identity: IdentityDep
):
    return service.update_project(session, identity, project_id, data)


@router.post("/projects/{project_id}/archive", response_model=ProjectOut)
def archive_project(
    project_id: UUID, data: VersionInput, session: SessionDep, identity: IdentityDep
):
    return service.update_project(session, identity, project_id, data, archive=True)
