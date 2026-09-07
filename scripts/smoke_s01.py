"""Live S01 web session/proxy smoke; uses only seeded local demo credentials."""

import json
from pathlib import Path
from uuid import uuid4

import httpx

origin = "http://127.0.0.1:3000"
credentials = json.loads(Path(".local/demo-credentials.json").read_text())
with httpx.Client(base_url=origin, trust_env=False, timeout=15) as client:
    response = client.post(
        "/api/session",
        json={"token": credentials["a-owner"]["token"]},
        headers={"Origin": "https://other.invalid"},
    )
    assert response.status_code == 403
    response = client.post(
        "/api/session", json={"token": credentials["a-owner"]["token"]}, headers={"Origin": origin}
    )
    assert response.status_code == 200, response.text
    cookies = response.headers.get_list("set-cookie")
    assert all("HttpOnly" in value and "SameSite=strict" in value for value in cookies)
    response = client.post(
        "/api/session",
        json={"organizationId": credentials["b-owner"]["organization_id"]},
        headers={"Origin": origin},
    )
    assert response.status_code == 403
    response = client.post(
        "/api/backend/customers",
        json={"name": "S01 smoke " + uuid4().hex[:8]},
        headers={"Origin": origin},
    )
    assert response.status_code == 201, response.text
    customer = response.json()
    response = client.patch(
        "/api/backend/customers/" + customer["id"],
        json={"name": "smoke 更新", "version": 1},
        headers={"Origin": origin},
    )
    assert response.status_code == 200, response.text
    response = client.post(
        "/api/backend/customers/" + customer["id"] + "/projects",
        json={"name": "smoke 项目"},
        headers={"Origin": origin},
    )
    assert response.status_code == 201, response.text
    project = response.json()
    assert (
        client.post(
            "/api/backend/projects/" + project["id"] + "/archive",
            json={"version": 1},
            headers={"Origin": origin},
        ).status_code
        == 200
    )
    assert (
        client.request(
            "DELETE",
            "/api/backend/customers/" + customer["id"],
            json={"version": 2},
            headers={"Origin": origin},
        ).status_code
        == 200
    )
    assert client.delete("/api/session", headers={"Origin": origin}).status_code == 200
    assert client.get("/api/backend/customers").status_code == 401
print("Live session, CSRF, tenant selection, CRUD/archive and logout: passed")
print("Archived smoke records retained as local demo evidence:", customer["id"], project["id"])
