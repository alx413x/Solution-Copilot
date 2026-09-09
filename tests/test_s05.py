from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from solution_copilot.application import conversation_jobs as jobs
from solution_copilot.application.conversation_schemas import ChatOutput
from solution_copilot.domain.models import AuditEvent, CustomerAccess, GenerationRun, Memory
from solution_copilot.infrastructure import generation
from sqlalchemy import delete, select
from test_s01 import db as db
from test_s01 import setup as setup


def start(client, h, customers):
    p = client.post(
        f"/api/v1/customers/{customers[0].id}/projects", headers=h(), json={"name": "S05"}
    ).json()["id"]
    c = client.post(f"/api/v1/projects/{p}/conversations", headers=h(), json={}).json()["id"]
    return p, c


def send(client, h, c, text="预算上限100万元", epoch=0, who="a-owner"):
    data = {"text": text, "epoch": epoch, "request_id": str(uuid4())}
    response = client.post(f"/api/v1/conversations/{c}/messages", headers=h(who), json=data)
    assert response.status_code == 202, response.text
    return response.json(), data


def reply(payload, context, memories):
    source = payload["source"]
    return ChatOutput(
        summary="预算",
        reply="已记录预算，请补充验收指标。",
        items=[
            dict(
                category="timeline_budget",
                title="预算",
                content=source["content"],
                confidence=0.9,
                source_id=source["source_id"],
                quote=source["content"],
            )
        ],
    ), {"model": "test"}


def test_dialogue_idempotence_quotes_events_and_answers(setup, db, monkeypatch):
    client, h, customers, _, _ = setup
    p, c = start(client, h, customers)
    base = f"/api/v1/projects/{p}"
    assert client.get(base + "/dialogue", headers=h("b-owner", 1)).status_code == 404
    assert (
        client.post(
            f"/api/v1/conversations/{c}/messages",
            headers=h("a-viewer"),
            json={"text": "x", "epoch": 0, "request_id": str(uuid4())},
        ).status_code
        == 403
    )
    monkeypatch.setattr(generation, "chat", reply)
    run, data = send(client, h, c)
    again = client.post(f"/api/v1/conversations/{c}/messages", headers=h(), json=data)
    assert again.json()["id"] == run["id"]
    db.rollback()
    jobs.run_job(run["id"])
    jobs.run_job(run["id"])
    db.expire_all()
    hist = client.get(f"/api/v1/conversations/{c}/messages", headers=h()).json()
    assert len(hist["messages"]) == 2 and hist["run"]["status"] == "waiting_user", hist
    profile = client.get(base + "/requirements", headers=h()).json()
    assert profile["items"][0]["sources"][0]["message_id"] == hist["messages"][0]["id"]
    stream = client.get(f"/api/v1/runs/{run['id']}/events", headers=h())
    assert "event: message.delta" in stream.text and "citation.created" in stream.text
    resumed = client.get(f"/api/v1/runs/{run['id']}/events", headers={**h(), "Last-Event-ID": "2"})
    assert "event: run.started" not in resumed.text and "message.delta" in resumed.text
    assert client.get(f"/api/v1/runs/{run['id']}/events?after=999", headers=h()).status_code == 422
    assert (
        client.get(f"/api/v1/runs/{run['id']}/events", headers=h("b-owner", 1)).status_code == 404
    )
    questions = client.post(base + "/clarifications", headers=h()).json()
    assert len(questions) == 9
    assert len(client.post(base + "/clarifications", headers=h()).json()) == 9
    required = next(q for q in questions if q["category"] == "goal")
    assert (
        client.post(
            f"/api/v1/clarifications/{required['id']}/skip", headers=h(), json={"version": 1}
        ).status_code
        == 409
    )
    db.rollback()
    answer = {
        "conversation_id": c,
        "answer": "将出稿时间缩短至1小时",
        "version": 1,
        "profile_version": profile["version"],
        "epoch": 0,
    }
    answered = client.post(
        f"/api/v1/clarifications/{required['id']}/answer", headers=h(), json=answer
    )
    assert answered.status_code == 200, answered.text
    assert answered.json()["status"] == "answered"
    assert (
        client.post(
            f"/api/v1/clarifications/{required['id']}/answer", headers=h(), json=answer
        ).status_code
        == 409
    )
    db.rollback()
    after = client.get(base + "/requirements", headers=h()).json()
    assert len(after["items"]) == 2 and after["items"][1]["confidence"] is None
    optional = next(q for q in questions if q["importance"] == "recommended")
    assert (
        client.post(
            f"/api/v1/clarifications/{optional['id']}/skip", headers=h(), json={"version": 1}
        ).json()["status"]
        == "skipped"
    )


def test_memory_scope_resets_context_and_late_publication(setup, db, monkeypatch):
    client, h, customers, _, _ = setup
    p, c = start(client, h, customers)
    base = f"/api/v1/projects/{p}"
    monkeypatch.setattr(generation, "chat", reply)
    run, _ = send(client, h, c)
    jobs.run_job(run["id"])
    db.expire_all()
    message = client.get(f"/api/v1/conversations/{c}/messages", headers=h()).json()["messages"][0]
    saved = {}
    for scope in ["conversation", "project", "customer"]:
        r = client.post(
            base + "/memories",
            headers=h(),
            json={"source_message_id": message["id"], "scope": scope, "content": scope},
        )
        assert r.status_code == 201, r.text
        m = r.json()
        assert m["status"] == "proposed"
        r = client.patch(
            f"/api/v1/memories/{m['id']}",
            headers=h(),
            json={"version": m["version"], "content": scope, "status": "confirmed"},
        )
        assert r.status_code == 200, r.text
        saved[scope] = r.json()
    preview = client.post(f"/api/v1/conversations/{c}/reset", headers=h(), json={}).json()
    assert (
        preview["memories"] == 1 and preview["context_messages"] == 2 and not preview["confirmed"]
    )
    assert len(client.get(base + "/memories", headers=h()).json()) == 3
    run, _ = send(client, h, c, "新的需求")
    reset = client.post(
        f"/api/v1/conversations/{c}/reset", headers=h(), json={"confirm": True}
    ).json()
    assert reset["runs"] == 2
    jobs.run_job(run["id"])
    db.expire_all()
    assert db.get(GenerationRun, UUID(run["id"])).status == "cancelled"
    memories = client.get(base + "/memories", headers=h()).json()
    assert {m["scope"] for m in memories} == {"project", "customer"}
    assert (
        len(client.get(f"/api/v1/conversations/{c}/messages", headers=h()).json()["messages"]) == 3
    )
    assert (
        client.post(base + "/memories/reset", headers=h(), json={"confirm": True}).json()[
            "memories"
        ]
        == 1
    )
    assert [m["scope"] for m in client.get(base + "/memories", headers=h()).json()] == ["customer"]
    # Customer memory is shared to another project, project and conversation memories are not.
    p2, _ = start(client, h, customers)
    assert len(client.get(f"/api/v1/projects/{p2}/memories", headers=h()).json()) == 1
    captured = []

    def checked(payload, context, memories):
        captured.append((context, memories))
        return ChatOutput(summary="", reply="收到", items=[]), {}

    monkeypatch.setattr(generation, "chat", checked)
    run, _ = send(client, h, c, "重置后的消息", epoch=1)
    jobs.run_job(run["id"])
    db.expire_all()
    assert len(captured[0][0]) == 1 and captured[0][1][0]["scope"] == "customer"
    assert list(db.scalars(select(AuditEvent).where(AuditEvent.action == "conversation.reset")))
    m = saved["customer"]
    assert (
        client.patch(
            f"/api/v1/memories/{m['id']}",
            headers=h(),
            json={"version": 1, "content": "stale", "status": "confirmed"},
        ).status_code
        == 409
    )
    db.rollback()

    # Reset while provider is in flight fences the eventual reply.
    def resetting(*args):
        client.post(f"/api/v1/conversations/{c}/reset", headers=h(), json={"confirm": True})
        return checked(*args)

    monkeypatch.setattr(generation, "chat", resetting)
    run, _ = send(client, h, c, "晚到消息", epoch=1)
    jobs.run_job(run["id"])
    db.expire_all()
    assert db.get(GenerationRun, UUID(run["id"])).status == "cancelled"
    assert db.get(Memory, UUID(m["id"])).status == "confirmed"


def test_revocation_cancel_lease_and_version_fencing(setup, db, monkeypatch):
    client, h, customers, users, _ = setup
    p, c = start(client, h, customers)
    monkeypatch.setattr(generation, "chat", reply)
    run, _ = send(client, h, c, who="a-member")
    db.execute(delete(CustomerAccess).where(CustomerAccess.user_id == users["a-member"][0].id))
    db.commit()
    jobs.run_job(run["id"])
    db.expire_all()
    assert db.get(GenerationRun, UUID(run["id"])).status == "failed"
    run, _ = send(client, h, c)
    client.post(f"/api/v1/runs/{run['id']}/cancel", headers=h())
    jobs.run_job(run["id"])
    db.expire_all()
    assert db.get(GenerationRun, UUID(run["id"])).status == "cancelled"
    run, _ = send(client, h, c)
    row = db.get(GenerationRun, UUID(run["id"]))
    row.status = "running"
    row.attempts = 1
    row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    sent = []
    jobs.dispatch_once(sent.append)
    assert sent == [run["id"]]

    def edit_during(*args):
        path = f"/api/v1/projects/{p}/requirements"
        v = client.get(path, headers=h()).json()["version"]
        client.patch(path, headers=h(), json={"version": v, "summary": "人工摘要"})
        return reply(*args)

    monkeypatch.setattr(generation, "chat", edit_during)
    jobs.run_job(run["id"])
    db.expire_all()
    assert db.get(GenerationRun, UUID(run["id"])).status == "failed"
    assert not client.get(f"/api/v1/projects/{p}/requirements", headers=h()).json()["items"]
    # Saved message lookup uses the same project ACL.
    message = client.get(f"/api/v1/conversations/{c}/messages", headers=h()).json()["messages"][0]
    assert client.get(f"/api/v1/messages/{message['id']}", headers=h()).status_code == 200
    assert (
        client.get(f"/api/v1/messages/{message['id']}", headers=h("b-owner", 1)).status_code == 404
    )
