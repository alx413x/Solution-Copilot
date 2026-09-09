from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from solution_copilot.application import requirement_jobs as jobs
from solution_copilot.application import requirements as service
from solution_copilot.application.errors import AppError
from solution_copilot.application.requirement_schemas import ExtractionOutput
from solution_copilot.domain.models import CustomerAccess, RequirementExtraction, RequirementProfile
from solution_copilot.infrastructure import generation
from sqlalchemy import delete
from test_s01 import db as db
from test_s01 import setup as setup


def output(content="预算上限 100 万元", relation="new", related_id=None):
    return ExtractionOutput(
        summary="项目预算",
        items=[
            dict(
                category="timeline_budget",
                title="预算",
                content=content,
                priority="must",
                confidence=0.9,
                source_id="text",
                quote=content,
                relation=relation,
                related_id=related_id,
            )
        ],
    )


def test_merge_retains_user_values_sources_and_rejects_invalid_quotes():
    profile = RequirementProfile(items=[], version=0, summary="", summary_edited=False)
    source = dict(source_id="text", type="user", title="输入", content="预算上限 100 万元")
    service.merge(profile, output(), [source])
    first = profile.items[0]
    first["status"], first["edited"] = "confirmed", True
    service.merge(profile, output(), [source])
    assert len(profile.items) == 1 and profile.items[0]["status"] == "confirmed"
    changed = dict(source, content="预算上限 80 万元")
    service.merge(profile, output(changed["content"], "duplicate", first["id"]), [changed])
    assert profile.items[0]["content"] == source["content"]
    assert profile.items[1]["status"] == "conflicted"
    before = profile.items
    with pytest.raises(AppError):
        service.merge(profile, output("不存在的引用"), [source])
    assert profile.items == before


def test_requirements_permissions_versions_conflicts_and_jobs(setup, db, monkeypatch):
    client, h, customers, users, _ = setup
    project = client.post(
        f"/api/v1/customers/{customers[0].id}/projects", headers=h(), json={"name": "需求测试"}
    ).json()
    path = f"/api/v1/projects/{project['id']}/requirements"
    assert client.get(path, headers=h("b-owner", 1)).status_code == 404
    assert client.patch(path, headers=h("a-viewer"), json={"version": 0}).status_code == 403
    monkeypatch.setattr(generation, "extract", lambda *_: (output(), {"model": "test"}))
    job = client.post(
        path + "/extractions", headers=h("a-member"), json={"text": "预算上限 100 万元"}
    ).json()
    assert client.post(path + "/extractions", headers=h(), json={"text": "重复"}).status_code == 409
    db.rollback()  # TestClient shares a Session; production dependencies close failed requests.
    jobs.run_job(job["id"])
    jobs.run_job(job["id"])
    db.expire_all()
    profile = client.get(path, headers=h()).json()
    assert profile["extraction"]["status"] == "succeeded" and len(profile["items"]) == 1
    confirmed = client.post(
        path + "/confirm", headers=h(), json={"version": profile["version"]}
    ).json()
    assert confirmed["confirmed_at"] and confirmed["items"][0]["status"] == "confirmed"
    assert (
        client.patch(path, headers=h(), json={"version": 0, "summary": "stale"}).status_code == 409
    )
    db.rollback()
    first = confirmed["items"][0]
    monkeypatch.setattr(
        generation, "extract", lambda *_: (output("预算上限 80 万元", "conflict", first["id"]), {})
    )
    job = client.post(path + "/extractions", headers=h(), json={"text": "预算上限 80 万元"}).json()
    jobs.run_job(job["id"])
    db.expire_all()
    profile = client.get(path, headers=h()).json()
    assert profile["items"][0]["status"] == "confirmed"
    assert (
        client.post(
            path + "/confirm", headers=h(), json={"version": profile["version"]}
        ).status_code
        == 409
    )
    db.rollback()
    resolved = client.patch(
        path,
        headers=h(),
        json={
            "version": profile["version"],
            "item_id": profile["items"][1]["id"],
            "resolve_with": "keep",
        },
    ).json()
    assert resolved["items"][1]["status"] == "rejected"
    assert resolved["items"][0]["status"] == "confirmed"

    # A user edit while the model is running invalidates the pending publication.
    def during_call(*_):
        current = client.get(path, headers=h()).json()
        assert (
            client.patch(
                path, headers=h(), json={"version": current["version"], "summary": "人工摘要"}
            ).status_code
            == 200
        )
        return output(), {}

    monkeypatch.setattr(generation, "extract", during_call)
    job = client.post(path + "/extractions", headers=h(), json={"text": "预算上限 100 万元"}).json()
    jobs.run_job(job["id"])
    db.expire_all()
    profile = client.get(path, headers=h()).json()
    assert profile["summary"] == "人工摘要" and profile["extraction"]["status"] == "failed"
    # Revoked authorization is checked again by the worker.
    job = client.post(
        path + "/extractions", headers=h("a-member"), json={"text": "预算上限 100 万元"}
    ).json()
    db.execute(delete(CustomerAccess).where(CustomerAccess.user_id == users["a-member"][0].id))
    db.commit()
    jobs.run_job(job["id"])
    db.expire_all()
    assert db.get(RequirementExtraction, job["id"]).status == "failed"
    # Cancellation and lease recovery reuse persisted state.
    job = client.post(path + "/extractions", headers=h(), json={"text": "预算上限 100 万元"}).json()
    assert client.post(path + f"/extractions/{job['id']}/cancel", headers=h()).status_code == 200
    jobs.run_job(job["id"])
    db.expire_all()
    assert db.get(RequirementExtraction, job["id"]).status == "cancelled"
    job = client.post(path + "/extractions", headers=h(), json={"text": "预算上限 100 万元"}).json()
    row = db.get(RequirementExtraction, job["id"])
    row.status, row.attempts = "running", 1
    row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    sent = []
    jobs.dispatch_once(sent.append)
    assert sent == [job["id"]]


def test_source_scope_and_archive(setup, db, monkeypatch):
    from test_s03 import add_document

    client, h, customers, _, orgs = setup
    p = client.post(
        f"/api/v1/customers/{customers[0].id}/projects", headers=h(), json={"name": "P"}
    ).json()
    path = f"/api/v1/projects/{p['id']}/requirements"
    other = add_document(db, orgs[0], "预算上限 100 万元", "customer", customers[1].id)
    assert (
        client.post(
            path + "/extractions", headers=h(), json={"document_ids": [str(other.id)]}
        ).status_code
        == 404
    )
    db.rollback()
    doc = add_document(db, orgs[0], "预算上限 100 万元")

    def from_document(sources, existing):
        result = output()
        result.items[0].source_id = sources[0]["source_id"]
        return result, {}

    monkeypatch.setattr(generation, "extract", from_document)
    job = client.post(
        path + "/extractions", headers=h(), json={"document_ids": [str(doc.id)]}
    ).json()
    jobs.run_job(job["id"])
    db.expire_all()
    profile = client.get(path, headers=h()).json()
    source = profile["items"][0]["sources"][0]
    assert source["document_id"] == str(doc.id) and source["section_path"] == ["安全"]
    assert source["line_start"] == 1
    saved = client.patch(
        path,
        headers=h(),
        json={
            "version": profile["version"],
            "item_id": profile["items"][0]["id"],
            "item": {
                "category": "timeline_budget",
                "title": "预算确认",
                "content": "预算上限 100 万元，需客户确认。",
                "priority": "must",
            },
        },
    ).json()
    assert saved["items"][0]["confidence"] is None and saved["items"][0]["sources"]
    job = client.post(
        path + "/extractions", headers=h(), json={"document_ids": [str(doc.id)]}
    ).json()
    doc.generation += 1
    db.commit()
    jobs.run_job(job["id"])
    db.expire_all()
    assert db.get(RequirementExtraction, job["id"]).status == "failed"
    assert (
        client.post(
            path + "/extractions", headers=h(), json={"document_ids": [str(uuid4())]}
        ).status_code
        == 404
    )
    assert client.post(path + "/extractions", headers=h(), json={}).status_code == 422
    client.post(f"/api/v1/projects/{p['id']}/archive", headers=h(), json={"version": p["version"]})
    assert client.post(path + "/extractions", headers=h(), json={"text": "需求"}).status_code == 409
