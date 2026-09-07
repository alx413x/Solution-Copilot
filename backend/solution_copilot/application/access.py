from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from solution_copilot.application.errors import forbidden, missing
from solution_copilot.domain.models import Customer, CustomerAccess, Membership, Project


@dataclass(frozen=True)
class Identity:
    user_id: UUID
    organization_id: UUID
    role: str


def resolve_identity(session: Session, user_id: UUID, organization_id: UUID) -> Identity:
    membership = session.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.organization_id == organization_id
        )
    )
    if membership is None:
        raise forbidden()
    return Identity(user_id, organization_id, membership.role)


def customer_scope(identity: Identity):
    filters = [Customer.organization_id == identity.organization_id]
    if identity.role != "owner":
        filters.append(
            Customer.id.in_(
                select(CustomerAccess.customer_id).where(
                    CustomerAccess.organization_id == identity.organization_id,
                    CustomerAccess.user_id == identity.user_id,
                )
            )
        )
    return filters


def get_customer(session: Session, identity: Identity, customer_id: UUID):
    customer = session.scalar(
        select(Customer).where(Customer.id == customer_id, *customer_scope(identity))
    )
    if customer is None:
        raise missing()
    return customer


def get_project(session: Session, identity: Identity, project_id: UUID):
    project = session.scalar(
        select(Project)
        .join(Customer, Customer.id == Project.customer_id)
        .where(
            Project.id == project_id,
            Project.organization_id == identity.organization_id,
            *customer_scope(identity),
        )
    )
    if project is None:
        raise missing()
    return project


def require_write(identity: Identity, owner_only=False):
    if identity.role == "viewer" or (owner_only and identity.role != "owner"):
        raise forbidden()
