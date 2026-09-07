"""Explicit local-only demo seed; never runs during application startup."""

import hashlib
import json
import os
import secrets
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from solution_copilot.config import get_settings
from solution_copilot.domain.models import Customer, CustomerAccess, Membership, Organization, User
from solution_copilot.infrastructure.database import get_engine
from sqlalchemy.orm import Session


def uid(name):
    return uuid5(NAMESPACE_URL, f"solution-copilot-demo/{name}")


def seed():
    if get_settings().app_env == "production" or not get_settings().dev_auth_enabled:
        raise SystemExit("Seed requires APP_ENV=development and DEV_AUTH_ENABLED=true")
    path = Path(".local/demo-credentials.json")
    if path.exists():
        raise SystemExit("Seed credentials already exist. Reuse .local/demo-credentials.json.")
    credentials = {}
    with Session(get_engine()) as session:
        for group in ["a", "b"]:
            org_id = uid(f"org-{group}")
            if session.get(Organization, org_id):
                raise SystemExit("Demo organization already exists; seed will not overwrite it.")
            session.add(
                Organization(id=org_id, name=f"示例组织 {group.upper()}", slug=f"demo-{group}")
            )
            session.flush()
            for role in ["owner", "member", "viewer"]:
                token = secrets.token_urlsafe(32)
                user_id = uid(f"{group}-{role}")
                session.add(
                    User(
                        id=user_id,
                        external_subject=f"demo:{group}:{role}",
                        email=f"{group}-{role}@example.invalid",
                        display_name=f"{group.upper()} {role}",
                        dev_token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    )
                )
                session.flush()
                session.add(Membership(organization_id=org_id, user_id=user_id, role=role))
                credentials[f"{group}-{role}"] = {"token": token, "organization_id": str(org_id)}
            session.flush()
            for number in [1, 2]:
                customer = Customer(
                    id=uid(f"{group}-customer-{number}"),
                    organization_id=org_id,
                    name=f"{group.upper()} 示例客户 {number}",
                    industry="制造业",
                    region="华东",
                )
                session.add(customer)
                session.flush()
                if number == 1:
                    for role in ["member", "viewer"]:
                        session.add(
                            CustomerAccess(
                                organization_id=org_id,
                                customer_id=customer.id,
                                user_id=uid(f"{group}-{role}"),
                            )
                        )
        # Write credentials only after DB constraints have been validated.
        session.flush()
        path.parent.mkdir(exist_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as file:
            json.dump(credentials, file, indent=2)
        session.commit()
    print("Demo data ready. Local credentials: .local/demo-credentials.json (not versioned)")


if __name__ == "__main__":
    seed()
