from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from solution_copilot.application.access import (
    customer_scope,
    get_customer,
    get_project,
    require_write,
)
from solution_copilot.application.errors import AppError
from solution_copilot.domain.models import Customer, Project


def commit(session: Session):
    try:
        session.commit()
    except StaleDataError:
        session.rollback()
        raise AppError(409, "VERSION_CONFLICT", "数据已更新，请刷新后重试。") from None


def check_version(record, version):
    if record.version != version:
        raise AppError(409, "VERSION_CONFLICT", "数据已更新，请刷新后重试。")


def active_customer(customer):
    if customer.deleted_at:
        raise AppError(409, "CUSTOMER_ARCHIVED", "客户已归档，无法修改。")


def list_customers(session, identity, limit, after, archived):
    statement = select(Customer).where(*customer_scope(identity))
    statement = statement.where(
        Customer.deleted_at.is_not(None) if archived else Customer.deleted_at.is_(None)
    )
    if after:
        statement = statement.where(Customer.id > after)
    items = list(session.scalars(statement.order_by(Customer.id).limit(limit + 1)))
    return {
        "items": items[:limit],
        "next_cursor": items[limit - 1].id if len(items) > limit else None,
    }


def create_customer(session, identity, data):
    require_write(identity, owner_only=True)
    record = Customer(organization_id=identity.organization_id, **data.model_dump())
    session.add(record)
    commit(session)
    return record


def update_customer(session, identity, customer_id, data):
    record = get_customer(session, identity, customer_id)
    require_write(identity)
    active_customer(record)
    check_version(record, data.version)
    for key, value in data.model_dump(exclude={"version"}, exclude_unset=True).items():
        setattr(record, key, value)
    commit(session)
    return record


def archive_customer(session, identity, customer_id, version):
    # Lock parent to serialize customer archival against project writes.
    session.execute(
        select(Customer)
        .where(Customer.id == customer_id, *customer_scope(identity))
        .with_for_update()
    )
    record = get_customer(session, identity, customer_id)
    require_write(identity)
    check_version(record, version)
    active_customer(record)
    record.deleted_at = datetime.now(UTC)
    commit(session)
    return record


def lock_customer(session, identity, customer_id):
    session.execute(
        select(Customer)
        .where(Customer.id == customer_id, *customer_scope(identity))
        .with_for_update()
    )
    record = get_customer(session, identity, customer_id)
    session.refresh(record)
    active_customer(record)
    return record


def create_project(session, identity, customer_id, data):
    require_write(identity)
    lock_customer(session, identity, customer_id)
    record = Project(
        organization_id=identity.organization_id,
        customer_id=customer_id,
        owner_user_id=identity.user_id,
        **data.model_dump(),
    )
    session.add(record)
    commit(session)
    return record


def list_projects(session, identity, limit, after, archived, customer_id: UUID | None):
    statement = (
        select(Project)
        .join(Customer, Customer.id == Project.customer_id)
        .where(Project.organization_id == identity.organization_id, *customer_scope(identity))
    )
    if archived:
        statement = statement.where(
            (Project.status == "archived") | Customer.deleted_at.is_not(None)
        )
    else:
        statement = statement.where(Project.status != "archived", Customer.deleted_at.is_(None))
    if customer_id:
        get_customer(session, identity, customer_id)
        statement = statement.where(Project.customer_id == customer_id)
    if after:
        statement = statement.where(Project.id > after)
    items = list(session.scalars(statement.order_by(Project.id).limit(limit + 1)))
    return {
        "items": items[:limit],
        "next_cursor": items[limit - 1].id if len(items) > limit else None,
    }


def update_project(session, identity, project_id, data, archive=False):
    record = get_project(session, identity, project_id)
    require_write(identity)
    lock_customer(session, identity, record.customer_id)
    if record.status == "archived":
        raise AppError(409, "PROJECT_ARCHIVED", "项目已归档，无法修改。")
    check_version(record, data.version)
    if archive:
        record.status = "archived"
    else:
        for key, value in data.model_dump(exclude={"version"}, exclude_unset=True).items():
            setattr(record, key, value)
    commit(session)
    return record
