"""PostgreSQL integration tests isolated in a random schema, never SQLite."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from solution_copilot.application.access import get_customer, resolve_identity
from solution_copilot.application.errors import AppError
from solution_copilot.config import Settings, get_settings
from solution_copilot.domain.models import Customer, CustomerAccess, Membership, Organization, User
from solution_copilot.infrastructure.database import get_engine, get_session
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from apps.api.main import app


@pytest.fixture
def db(monkeypatch):
    if os.environ.get("RUN_DB_TESTS") != "1":
        pytest.skip("Set RUN_DB_TESTS=1 to run PostgreSQL integration tests")
    from alembic import command
    from alembic.config import Config

    engine = get_engine()
    schema = "s01_test_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {schema}"))
    isolated = create_engine(engine.url, connect_args={"options": f"-csearch_path={schema}"})
    monkeypatch.setattr("solution_copilot.infrastructure.database.get_engine", lambda: isolated)
    try:
        command.upgrade(Config("alembic.ini"), "head")
        with Session(isolated) as session:
            yield session
    finally:
        isolated.dispose()
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))


@pytest.fixture
def setup(db, monkeypatch):
    settings = get_settings().model_copy(update={"dev_auth_enabled": True, "app_env": "test"})
    monkeypatch.setattr("apps.api.auth.get_settings", lambda: settings)
    organizations = []
    users = {}
    customers = []
    for group in ["a", "b"]:
        org = Organization(name=group, slug=group)
        db.add(org)
        db.flush()
        organizations.append(org)
        for role in ["owner", "member", "viewer"]:
            token = f"{group}-{role}-test-only"
            user = User(
                external_subject=f"{group}-{role}",
                email=f"{group}-{role}@example.invalid",
                display_name=role,
                dev_token_hash=hashlib.sha256(token.encode()).hexdigest(),
            )
            db.add(user)
            db.flush()
            db.add(Membership(organization_id=org.id, user_id=user.id, role=role))
            users[f"{group}-{role}"] = (user, token)
        db.flush()
        for number in [1, 2]:
            customer = Customer(organization_id=org.id, name=f"{group}-{number}")
            db.add(customer)
            db.flush()
            customers.append(customer)
            if number == 1:
                for role in ["member", "viewer"]:
                    db.add(
                        CustomerAccess(
                            organization_id=org.id,
                            customer_id=customer.id,
                            user_id=users[f"{group}-{role}"][0].id,
                        )
                    )
    db.commit()
    app.dependency_overrides[get_session] = lambda: db

    def headers(who="a-owner", org=0):
        return {
            "Authorization": f"Bearer {users[who][1]}",
            "X-Organization-ID": str(organizations[org].id),
        }

    try:
        yield TestClient(app), headers, customers, users, organizations
    finally:
        app.dependency_overrides.clear()


def test_isolation_roles_and_identity(setup, db):
    client, h, customers, users, orgs = setup
    assert client.get("/api/v1/customers").status_code == 401
    assert (
        client.get(
            "/api/v1/customers", headers={**h(), "Authorization": "Bearer forged"}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/customers", headers=h(org=1)).status_code == 403
    assert len(client.get("/api/v1/customers", headers=h()).json()["items"]) == 2
    assert len(client.get("/api/v1/customers", headers=h("a-member")).json()["items"]) == 1
    for customer in [customers[1], customers[2]]:
        path = f"/api/v1/customers/{customer.id}"
        assert client.get(path, headers=h("a-member")).status_code == 404
        assert (
            client.patch(
                path, headers=h("a-member"), json={"name": "bad", "version": 1}
            ).status_code
            == 404
        )
    assert (
        client.post("/api/v1/customers", headers=h("a-viewer"), json={"name": "bad"}).status_code
        == 403
    )
    path = f"/api/v1/customers/{customers[0].id}"
    assert (
        client.patch(path, headers=h("a-viewer"), json={"name": "bad", "version": 1}).status_code
        == 403
    )
    assert (
        client.post(path + "/projects", headers=h("a-viewer"), json={"name": "bad"}).status_code
        == 403
    )
    # Shared application authorization is reusable by workers, with fresh membership lookup.
    identity = resolve_identity(db, users["a-member"][0].id, orgs[0].id)
    with pytest.raises(AppError):
        get_customer(db, identity, customers[1].id)
    membership = db.scalar(select(Membership).where(Membership.user_id == identity.user_id))
    grant = db.scalar(select(CustomerAccess).where(CustomerAccess.user_id == identity.user_id))
    db.delete(grant)
    db.flush()
    db.delete(membership)
    db.commit()
    with pytest.raises(AppError):
        resolve_identity(db, identity.user_id, identity.organization_id)


def test_crud_versions_archive_and_pagination(setup):
    client, h, customers, _, _ = setup
    first = client.get("/api/v1/customers?limit=1", headers=h()).json()
    second = client.get(
        "/api/v1/customers?limit=1&after=" + first["next_cursor"], headers=h()
    ).json()
    assert first["items"][0]["id"] != second["items"][0]["id"]
    created = client.post(
        "/api/v1/customers", headers=h(), json={"name": "新客户", "industry": "工业"}
    ).json()
    path = "/api/v1/customers/" + created["id"]
    update = client.patch(path, headers=h(), json={"name": "更新客户", "version": 1})
    assert update.status_code == 200 and update.json()["version"] == 2
    assert client.patch(path, headers=h(), json={"name": "旧写入", "version": 1}).status_code == 409
    project = client.post(path + "/projects", headers=h(), json={"name": "项目"}).json()
    p = "/api/v1/projects/" + project["id"]
    assert client.get(p, headers=h("b-owner", 1)).status_code == 404
    assert (
        client.patch(
            p, headers=h(), json={"name": "更新", "version": 1, "status": "completed"}
        ).status_code
        == 422
    )
    assert (
        client.patch(p, headers=h(), json={"name": "更新项目", "version": 1}).json()["version"] == 2
    )
    assert client.post(p + "/archive", headers=h(), json={"version": 1}).status_code == 409
    assert (
        client.post(p + "/archive", headers=h(), json={"version": 2}).json()["status"] == "archived"
    )
    assert client.patch(p, headers=h(), json={"name": "bad", "version": 3}).status_code == 409
    assert client.request("DELETE", path, headers=h(), json={"version": 2}).status_code == 200
    assert client.post(path + "/projects", headers=h(), json={"name": "bad"}).status_code == 409
    assert all(
        c["id"] != created["id"]
        for c in client.get("/api/v1/customers", headers=h()).json()["items"]
    )
    assert created["id"] in [
        c["id"] for c in client.get("/api/v1/customers?archived=true", headers=h()).json()["items"]
    ]
    assert (
        client.post(
            "/api/v1/customers", headers=h(), json={"name": " ", "organization_id": str(uuid4())}
        ).status_code
        == 422
    )


def test_production_rejects_development_auth():
    with pytest.raises(ValidationError):
        Settings(app_env="production", dev_auth_enabled=True)


def test_jwt_validation(setup, monkeypatch):
    from types import SimpleNamespace

    client, h, _, users, _ = setup
    settings = get_settings().model_copy(
        update={
            "dev_auth_enabled": False,
            "oidc_jwks_url": "https://identity.example/jwks",
            "oidc_issuer": "https://identity.example",
            "oidc_audience": "solution-api",
        }
    )
    monkeypatch.setattr("apps.api.auth.get_settings", lambda: settings)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        "apps.api.auth.jwks_client",
        lambda _: SimpleNamespace(
            get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key())
        ),
    )
    claims = {
        "sub": users["a-owner"][0].external_subject,
        "iss": settings.oidc_issuer,
        "aud": settings.oidc_audience,
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }

    def request(payload, signing_key=key):
        token = jwt.encode(payload, signing_key, algorithm="RS256")
        return client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert request(claims).status_code == 200
    for bad in [
        {"aud": "wrong"},
        {"iss": "wrong"},
        {"exp": datetime.now(UTC) - timedelta(seconds=1)},
    ]:
        assert request({**claims, **bad}).status_code == 401
    assert request({k: v for k, v in claims.items() if k != "exp"}).status_code == 401
    assert (
        request(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048)).status_code
        == 401
    )


def test_database_rejects_cross_tenant_links_and_stale_updates(setup, db):
    from solution_copilot.domain.models import Project
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm.exc import StaleDataError

    _, _, customers, users, orgs = setup
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.add(
                Project(
                    organization_id=orgs[0].id,
                    customer_id=customers[2].id,
                    owner_user_id=users["a-owner"][0].id,
                    name="invalid",
                )
            )
            db.flush()
    with Session(db.bind) as other:
        left = db.get(Customer, customers[0].id)
        right = other.get(Customer, customers[0].id)
        right.name = "concurrent change"
        other.commit()
        left.name = "stale overwrite"
        with pytest.raises(StaleDataError):
            db.commit()
        db.rollback()


def test_customer_archive_blocks_existing_project_and_patch_preserves_fields(setup):
    client, h, customers, _, _ = setup
    path = f"/api/v1/customers/{customers[0].id}"
    response = client.patch(path, headers=h(), json={"industry": "制造", "version": 1})
    assert response.status_code == 200 and response.json()["name"] == "a-1"
    assert client.patch(path, headers=h(), json={"name": None, "version": 2}).status_code == 422
    project = client.post(path + "/projects", headers=h(), json={"name": "归档保护"}).json()
    assert client.request("DELETE", path, headers=h(), json={"version": 2}).status_code == 200
    assert (
        client.patch(
            "/api/v1/projects/" + project["id"], headers=h(), json={"name": "bad", "version": 1}
        ).status_code
        == 409
    )


def test_migration_round_trip(db):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect

    config = Config("alembic.ini")
    assert "projects" in inspect(db.bind).get_table_names()
    command.downgrade(config, "base")
    assert "projects" not in inspect(db.bind).get_table_names()
    command.upgrade(config, "head")
    assert "customer_access" in inspect(db.bind).get_table_names()


def test_development_auth_is_opt_in():
    assert (
        Settings(
            _env_file=None,
            database_url="postgresql://unused",
            redis_url="redis://unused",
            s3_endpoint_url="http://unused",
            s3_access_key="unused",
            s3_secret_key="unused",
        ).dev_auth_enabled
        is False
    )


def test_member_project_scope_and_viewer_archive_denial(setup):
    client, h, customers, _, _ = setup
    accessible = f"/api/v1/customers/{customers[0].id}"
    hidden = f"/api/v1/customers/{customers[1].id}"
    own = client.post(accessible + "/projects", headers=h("a-member"), json={"name": "成员项目"})
    assert own.status_code == 201
    hidden_project = client.post(
        hidden + "/projects", headers=h(), json={"name": "隐藏项目"}
    ).json()
    assert (
        client.post(hidden + "/projects", headers=h("a-member"), json={"name": "bad"}).status_code
        == 404
    )
    path = "/api/v1/projects/" + hidden_project["id"]
    assert client.get(path, headers=h("a-member")).status_code == 404
    assert (
        client.patch(path, headers=h("a-member"), json={"name": "bad", "version": 1}).status_code
        == 404
    )
    assert (
        client.post(path + "/archive", headers=h("a-member"), json={"version": 1}).status_code
        == 404
    )
    visible = client.get("/api/v1/projects", headers=h("a-viewer")).json()["items"]
    assert [item["id"] for item in visible] == [own.json()["id"]]
    assert (
        client.post(
            "/api/v1/projects/" + own.json()["id"] + "/archive",
            headers=h("a-viewer"),
            json={"version": 1},
        ).status_code
        == 403
    )
    assert (
        client.request("DELETE", accessible, headers=h("a-viewer"), json={"version": 1}).status_code
        == 403
    )
