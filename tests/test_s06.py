import os
import subprocess
import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4

from solution_copilot.application import conversation_jobs as jobs
from solution_copilot.application import workflows
from solution_copilot.application.requirement_schemas import REQUIRED
from solution_copilot.domain.models import GenerationRun, Message, RequirementProfile
from sqlalchemy import func, select, text
from test_s01 import db as db
from test_s01 import setup as setup
from test_s05 import start


def test_workflow_gates_restart_and_idempotence(setup, db, monkeypatch):
    client, h, customers, _, _ = setup
    p, c = start(client, h, customers)
    path = f"/api/v1/conversations/{c}/workflows"
    data = dict(goal="需求方案", epoch=0, request_id=str(uuid4()))
    response = client.post(path, headers=h(), json=data)
    assert response.status_code == 202, response.text
    run = response.json()["id"]
    assert client.post(path, headers=h(), json=data).json()["id"] == run
    assert (
        client.post(
            f"/api/v1/conversations/{c}/messages",
            headers=h(),
            json={"text": "复用编号", "epoch": 0, "request_id": data["request_id"]},
        ).status_code
        == 409
    )
    db.rollback()
    jobs.run_job(run)
    db.expire_all()
    row = db.get(GenerationRun, UUID(run))
    assert row.status == "waiting_user", row.error_message
    assert row.workflow["gate"] == 1
    assert db.scalar(text("SELECT count(*) FROM checkpoints")) > 0
    resume = dict(gate=1, approve=True, request_id=str(uuid4()))
    url = f"/api/v1/runs/{run}/resume"
    assert client.post(url, headers=h(), json=resume).status_code == 409
    db.rollback()
    profile = db.scalar(select(RequirementProfile).where(RequirementProfile.project_id == UUID(p)))
    profile.items = [
        dict(category=c, status="confirmed", content="测试需求", sources=[]) for c in REQUIRED
    ]
    profile.confirmed_at = datetime.now(UTC)
    profile.version += 1
    db.commit()
    monkeypatch.setattr(workflows.retrieval, "search", lambda *a: {"items": []})
    assert client.post(url, headers=h(), json=resume).status_code == 202
    db.rollback()
    # Every invocation builds a fresh graph/saver, with no in-memory checkpoint state.
    jobs.run_job(run)
    db.expire_all()
    row = db.get(GenerationRun, UUID(run))
    assert row.status == "waiting_user", row.error_message
    assert row.workflow["gate"] == 2 and len(row.workflow["outline"]) == 14
    assert client.post(url, headers=h(), json=resume).json()["status"] == "waiting_user"
    decision = dict(gate=2, approve=True, request_id=str(uuid4()))
    assert client.post(url, headers=h("a-viewer"), json=decision).status_code == 403
    db.rollback()
    assert client.post(url, headers=h(), json=decision).status_code == 202
    db.rollback()
    schema = db.scalar(text("SELECT current_schema()"))
    env = {
        **os.environ,
        "DATABASE_URL": db.bind.url.update_query_dict(
            {"options": f"-csearch_path={schema},public"}
        ).render_as_string(hide_password=False),
    }
    db.rollback()
    crash = """
import os, sys
from uuid import UUID
from sqlalchemy.orm import Session
from solution_copilot.infrastructure.database import get_engine
from solution_copilot.application.conversation_jobs import checked_run
from solution_copilot.application.workflows import advance
with Session(get_engine()) as session:
    row, conversation, project = checked_run(session, UUID(sys.argv[1]))
    advance(session, row, conversation, project)
    os._exit(19)
"""
    assert (
        subprocess.run(
            [sys.executable, "-c", crash, run], env=env, capture_output=True, timeout=30
        ).returncode
        == 19
    )
    assert db.get(GenerationRun, UUID(run)).status == "queued"
    assert (
        db.scalar(select(func.count()).select_from(Message).where(Message.run_id == UUID(run))) == 0
    )
    db.rollback()
    restarted = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from solution_copilot.application.conversation_jobs import run_job; "
            "run_job(sys.argv[1])",
            run,
        ],
        env=env,
        capture_output=True,
        timeout=30,
    )
    assert restarted.returncode == 0, restarted.stderr.decode()
    jobs.run_job(run)
    db.expire_all()
    assert db.get(GenerationRun, UUID(run)).status == "succeeded"
    assert client.post(url, headers=h(), json=decision).json()["status"] == "succeeded"
    assert (
        db.scalar(select(func.count()).select_from(Message).where(Message.run_id == UUID(run))) == 1
    )
    stream = client.get(f"/api/v1/runs/{run}/events", headers=h())
    assert "run.completed" in stream.text


def test_workflow_rejects_profile_change_after_gate_one_resume(setup, db):
    client, h, customers, _, _ = setup
    project_id, conversation_id = start(client, h, customers)
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/workflows",
        headers=h(),
        json={"goal": "需求方案", "epoch": 0, "request_id": str(uuid4())},
    )
    run = response.json()["id"]
    db.rollback()
    jobs.run_job(run)
    profile = db.scalar(
        select(RequirementProfile).where(RequirementProfile.project_id == UUID(project_id))
    )
    profile.items = [
        dict(category=category, status="confirmed", content="测试需求", sources=[])
        for category in REQUIRED
    ]
    profile.confirmed_at = datetime.now(UTC)
    profile.version += 1
    db.commit()
    assert (
        client.post(
            f"/api/v1/runs/{run}/resume",
            headers=h(),
            json={"gate": 1, "approve": True, "request_id": str(uuid4())},
        ).status_code
        == 202
    )
    db.rollback()
    profile.version += 1
    db.commit()
    jobs.run_job(run)
    db.expire_all()
    assert db.get(GenerationRun, UUID(run)).status == "failed"


def test_workflow_stale_sources_profile_and_revocation(setup, db, monkeypatch):
    from solution_copilot.domain.models import CustomerAccess, DocumentChunk
    from solution_copilot.infrastructure import embeddings
    from sqlalchemy import delete
    from test_s03 import add_document

    client, h, customers, users, orgs = setup
    p, c = start(client, h, customers)
    profile = RequirementProfile(
        organization_id=orgs[0].id,
        project_id=UUID(p),
        version=1,
        items=[
            dict(category=category, status="confirmed", content="测试", sources=[])
            for category in REQUIRED
        ],
        confirmed_at=datetime.now(UTC),
    )
    db.add(profile)
    db.commit()
    doc = add_document(db, orgs[0], "需求方案安全", "project", customers[0].id, UUID(p))
    monkeypatch.setattr(embeddings, "embed_query", lambda _: [1.0] + [0.0] * 511)
    path = f"/api/v1/conversations/{c}/workflows"
    for reason in ("source", "profile", "revocation", "cancel", "reset"):
        data = dict(goal="需求方案", epoch=0, request_id=str(uuid4()))
        r = client.post(path, headers=h("a-member"), json=data)
        assert r.status_code == 202, r.text
        run = r.json()["id"]
        db.rollback()
        jobs.run_job(run)
        db.expire_all()
        row = db.get(GenerationRun, UUID(run))
        assert row.status == "waiting_user", row.error_message
        assert row.workflow["gate"] == 2
        assert row.payload["snapshot"]["evidence"]
        assert client.get(path + "/latest", headers=h("b-owner", 1)).status_code == 404
        db.rollback()
        decision = dict(gate=2, approve=True, request_id=str(uuid4()))
        url = f"/api/v1/runs/{run}/resume"
        if reason == "source":
            doc = db.merge(doc)
            doc.status = "disabled"
            db.commit()
            assert client.post(url, headers=h(), json=decision).status_code == 409
            db.rollback()
            doc.status = "ready"
            db.commit()
        assert client.post(url, headers=h("a-member"), json=decision).status_code == 202
        db.rollback()
        if reason == "source":
            chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == doc.id))
            chunk.embedding_profile = "obsolete"
        elif reason == "profile":
            profile = db.merge(profile)
            profile.version += 1
        elif reason == "revocation":
            db.execute(
                delete(CustomerAccess).where(CustomerAccess.user_id == users["a-member"][0].id)
            )
        elif reason == "cancel":
            client.post(f"/api/v1/runs/{run}/cancel", headers=h())
        else:
            client.post(f"/api/v1/conversations/{c}/reset", headers=h(), json={"confirm": True})
        db.commit()
        jobs.run_job(run)
        db.expire_all()
        assert db.get(GenerationRun, UUID(run)).status == (
            "cancelled" if reason in {"cancel", "reset"} else "failed"
        )
        assert (
            db.scalar(select(func.count()).select_from(Message).where(Message.run_id == UUID(run)))
            == 0
        )
        if reason == "source":
            chunk.embedding_profile = embeddings.PROFILE
        if reason == "revocation":
            db.add(
                CustomerAccess(
                    organization_id=orgs[0].id,
                    customer_id=customers[0].id,
                    user_id=users["a-member"][0].id,
                )
            )
        db.commit()
