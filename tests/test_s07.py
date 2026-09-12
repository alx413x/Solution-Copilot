from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from solution_copilot.application import conversation_jobs, solution_jobs
from solution_copilot.application.requirement_schemas import REQUIRED
from solution_copilot.application.solution_schemas import (
    OutlineIdea,
    OutlineOutput,
    Paragraph,
    SectionOutput,
    SourceClaim,
)
from solution_copilot.domain.models import (
    CustomerAccess,
    GenerationRun,
    RequirementProfile,
    Solution,
    SolutionVersion,
)
from solution_copilot.infrastructure import embeddings, generation
from sqlalchemy import delete, func, select
from test_s01 import db as db
from test_s01 import setup as setup
from test_s03 import add_document
from test_s05 import start


def ready_solution(setup, db, monkeypatch, actor="a-owner"):
    client, h, customers, users, orgs = setup
    project_id, conversation_id = start(client, h, customers)
    project_id, conversation_id = UUID(project_id), UUID(conversation_id)
    profile = RequirementProfile(
        organization_id=orgs[0].id,
        project_id=project_id,
        version=1,
        summary="客户需要安全可靠的身份认证方案",
        items=[
            dict(
                id=str(uuid4()),
                category=category,
                title=f"{category}需求",
                content="系统必须支持单点登录和权限隔离",
                priority="must",
                status="confirmed",
                confidence=None,
                sources=[],
                edited=True,
                conflicts_with=[],
            )
            for category in REQUIRED
        ],
        confirmed_at=datetime.now(UTC),
        confirmed_by=users[actor][0].id,
    )
    workflow = GenerationRun(
        organization_id=orgs[0].id,
        project_id=project_id,
        conversation_id=conversation_id,
        actor_user_id=users[actor][0].id,
        request_id=uuid4(),
        status="succeeded",
        payload={
            "kind": "workflow",
            "epoch": 0,
            "snapshot": {"profile_version": 1, "evidence": []},
            "workflow": {
                "stage": "ready_for_generation",
                "gate": 0,
                "outline": [
                    {"id": "section-01", "title": "原始章节 A"},
                    {"id": "section-02", "title": "原始章节 B"},
                ],
                "warnings": [],
            },
        },
        events=[],
    )
    db.add_all([profile, workflow])
    db.commit()
    doc = add_document(
        db,
        orgs[0],
        "产品支持单点登录，并通过角色权限实现客户数据隔离。",
        "project",
        customers[0].id,
        project_id,
    )
    monkeypatch.setattr(embeddings, "embed_query", lambda _: [1.0] + [0.0] * 511)
    response = client.post(
        f"/api/v1/projects/{project_id}/solutions",
        headers=h(actor),
        json={"workflow_run_id": str(workflow.id), "title": "身份治理方案"},
    )
    assert response.status_code == 201, response.text
    return client, h, customers, users, orgs, doc, response.json(), workflow


def document_source(data):
    return next(source for source in data["sources"] if source["source_type"] == "document")


def outline_result(data, bad=False):
    source = document_source(data)
    quote = "产品支持单点登录" + ("（伪造）" if bad else "")
    return (
        OutlineOutput(
            sections=[
                OutlineIdea(
                    title="总体架构",
                    text="采用统一身份治理",
                    sources=[SourceClaim(source_id=source["source_id"], quote=quote)],
                ),
                OutlineIdea(
                    title="安全控制",
                    text="隔离客户数据",
                    sources=[
                        SourceClaim(source_id=source["source_id"], quote="角色权限实现客户数据隔离")
                    ],
                ),
            ]
        ),
        {"model": "test"},
    )


def section_result(data, suffix=""):
    source = document_source(data)
    return (
        SectionOutput(
            paragraphs=[
                Paragraph(
                    text=data["section"]["title"] + suffix,
                    sources=[SourceClaim(source_id=source["source_id"], quote="产品支持单点登录")],
                )
            ]
        ),
        {"model": "test"},
    )


def start_generation(client, h, solution, path, who="a-owner", **extra):
    body = {
        "version": solution["version"],
        "request_id": str(uuid4()),
        "instruction": "仅依据资料生成",
        **extra,
    }
    response = client.post(f"/api/v1/solutions/{solution['id']}/{path}", headers=h(who), json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


def test_solution_lifecycle_citations_partial_resume_and_history(setup, db, monkeypatch):
    client, h, _, _, _, doc, solution, workflow = ready_solution(setup, db, monkeypatch)
    base = f"/api/v1/solutions/{solution['id']}"

    assert client.get(base, headers=h("b-owner", 1)).status_code == 404
    viewer = client.get(base, headers=h("a-viewer"))
    assert viewer.status_code == 200 and viewer.json()["writable"] is False
    assert (
        client.post(
            base + "/outline",
            headers=h("a-viewer"),
            json={"version": 1, "request_id": str(uuid4())},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/projects/{solution['project_id']}/solutions",
            headers=h(),
            json={"workflow_run_id": str(workflow.id), "title": "另一标题"},
        ).status_code
        == 409
    )

    monkeypatch.setattr(
        generation, "solution", lambda data, outline=False: outline_result(data, True)
    )
    run, _ = start_generation(client, h, solution, "outline")
    db.rollback()
    solution_jobs.run_job(run["id"])
    db.expire_all()
    assert db.get(GenerationRun, UUID(run["id"])).status == "failed"
    assert db.get(Solution, UUID(solution["id"])).version == 1

    monkeypatch.setattr(generation, "solution", lambda data, outline=False: outline_result(data))
    solution = client.get(base, headers=h()).json()
    run, _ = start_generation(client, h, solution, "outline")
    db.rollback()
    conversation_jobs.run_job(run["id"])
    db.expire_all()
    solution = client.get(base, headers=h()).json()
    assert solution["version"] == 2 and [s["title"] for s in solution["current"]["sections"]] == [
        "总体架构",
        "安全控制",
    ]
    first_ids = [section["id"] for section in solution["current"]["sections"]]

    profile = db.scalar(
        select(RequirementProfile).where(
            RequirementProfile.project_id == UUID(solution["project_id"])
        )
    )
    profile.version += 1
    db.commit()
    approval = {
        "version": solution["version"],
        "request_id": str(uuid4()),
        "sections": [
            {"id": first_ids[1], "title": "安全控制", "goal": "隔离客户数据"},
            {"id": str(uuid4()), "title": "交付计划", "goal": "按期上线"},
        ],
    }
    assert client.post(base + "/outline/approve", headers=h(), json=approval).status_code == 409

    run, _ = start_generation(client, h, solution, "outline")
    db.rollback()
    solution_jobs.run_job(run["id"])
    solution = client.get(base, headers=h()).json()
    current_ids = [section["id"] for section in solution["current"]["sections"]]
    added_id = str(uuid4())
    approval.update(
        version=solution["version"],
        request_id=str(uuid4()),
        sections=[
            {"id": current_ids[1], "title": "安全控制", "goal": "隔离客户数据"},
            {"id": added_id, "title": "交付计划", "goal": "按期上线"},
        ],
    )
    approved = client.post(base + "/outline/approve", headers=h(), json=approval)
    assert approved.status_code == 202, approved.text
    db.rollback()
    solution = client.get(base, headers=h()).json()
    assert [s["id"] for s in solution["current"]["sections"]] == [current_ids[1], added_id]

    calls, provider_errors = 0, []

    def partial(data, outline=False):
        nonlocal calls
        calls += 1
        if calls == 1:
            try:
                return section_result(data)
            except Exception as exc:
                provider_errors.append(repr(exc))
                raise
        return section_result(data, "（失败）")[0].model_copy(
            update={
                "paragraphs": [
                    Paragraph(
                        text="无效章节",
                        sources=[SourceClaim(source_id="not-authorized", quote="伪造")],
                    )
                ]
            }
        ), {"model": "test"}

    monkeypatch.setattr(generation, "solution", partial)
    run_id = approved.json()["id"]
    solution_jobs.run_job(run_id)
    solution_jobs.run_job(run_id)
    db.expire_all()
    failed = db.get(GenerationRun, UUID(run_id))
    solution = client.get(base, headers=h()).json()
    assert failed.status == "failed" and solution["version"] == approval["version"] + 2, (
        failed.error_message,
        calls,
        provider_errors,
    )
    completed = solution["current"]["sections"][0]
    assert (
        completed["status"] == "draft" and solution["current"]["sections"][1]["status"] == "pending"
    )

    monkeypatch.setattr(
        generation, "solution", lambda data, outline=False: section_result(data, "（续写）")
    )
    retry, _ = start_generation(
        client, h, solution, f"sections/{solution['current']['sections'][1]['id']}/generate"
    )
    row = db.get(GenerationRun, UUID(retry["id"]))
    row.status, row.attempts = "running", 1
    row.lease_until = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    sent = []
    conversation_jobs.dispatch_once(sent.append)
    assert sent == [retry["id"]]
    solution_jobs.run_job(retry["id"])
    solution_jobs.run_job(retry["id"])
    db.expire_all()
    solution = client.get(base, headers=h()).json()
    assert solution["version"] == approval["version"] + 3
    assert solution["current"]["sections"][0] == completed
    assert (
        "续写" in solution["current"]["sections"][1]["content"]["content"][0]["content"][0]["text"]
    )
    assert (
        db.scalar(
            select(func.count())
            .select_from(SolutionVersion)
            .where(SolutionVersion.solution_id == UUID(solution["id"]))
        )
        == solution["version"]
    )

    history = client.get(base + "/versions", headers=h()).json()
    cited_number = next(
        item["version"] for item in history if item["change_summary"].startswith("生成章节")
    )
    before_delete = client.get(base + f"/versions/{cited_number}", headers=h()).json()
    citation = before_delete["sections"][0]["citations"][0]
    assert citation["document_id"] == str(doc.id) and citation["quote"] == "产品支持单点登录"
    assert client.delete(f"/api/v1/documents/{doc.id}", headers=h()).status_code == 200
    assert client.get(f"/api/v1/documents/{doc.id}/chunks", headers=h()).status_code == 404
    after_delete = client.get(base + f"/versions/{cited_number}", headers=h()).json()
    assert after_delete["sections"][0]["citations"][0] == citation


def test_manual_edit_validation_idempotence_and_unverified_citations(setup, db, monkeypatch):
    client, h, _, _, _, _, solution, _ = ready_solution(setup, db, monkeypatch)
    row = db.get(Solution, UUID(solution["id"]))
    row.status = "draft"
    db.commit()
    base = f"/api/v1/solutions/{solution['id']}"
    section_id = solution["current"]["sections"][0]["id"]
    monkeypatch.setattr(generation, "solution", lambda data, outline=False: section_result(data))
    run, _ = start_generation(client, h, solution, f"sections/{section_id}/generate")
    db.rollback()
    solution_jobs.run_job(run["id"])
    solution = client.get(base, headers=h()).json()
    assert solution["current"]["sections"][0]["citations"][0]["verification_status"] == "partial"
    request_id = str(uuid4())
    body = {
        "version": 2,
        "request_id": request_id,
        "section_id": section_id,
        "content": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "人工修订", "marks": [{"type": "bold"}]}],
                }
            ],
        },
        "change_summary": "修正文案",
    }
    edited = client.patch(base, headers=h(), json=body)
    assert edited.status_code == 200, edited.text
    assert edited.json()["version"] == 3
    assert (
        edited.json()["current"]["sections"][0]["citations"][0]["verification_status"]
        == "unverified"
    )
    assert client.patch(base, headers=h(), json=body).json()["version"] == 3
    conflict = {**body, "change_summary": "复用请求号"}
    assert client.patch(base, headers=h(), json=conflict).status_code == 409
    stale = {**body, "request_id": str(uuid4())}
    assert client.patch(base, headers=h(), json=stale).status_code == 409

    bad_nodes = [
        {"type": "doc", "content": [{"type": "script", "content": []}]},
        {
            "type": "doc",
            "content": [{"type": "paragraph", "attrs": {"onclick": "alert(1)"}}],
        },
        {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [
                        {
                            "type": "text",
                            "text": "链接",
                            "marks": [{"type": "link", "attrs": {"href": "javascript:alert(1)"}}],
                        }
                    ],
                }
            ],
        },
    ]
    for content in bad_nodes:
        invalid = {**body, "version": 3, "request_id": str(uuid4()), "content": content}
        assert client.patch(base, headers=h(), json=invalid).status_code == 422


def test_late_model_results_are_fenced(setup, db, monkeypatch):
    client, h, customers, users, orgs, _, solution, _ = ready_solution(setup, db, monkeypatch)
    base = f"/api/v1/solutions/{solution['id']}"
    row = db.get(Solution, UUID(solution["id"]))
    row.status = "draft"
    db.commit()
    section_id = solution["current"]["sections"][0]["id"]

    for reason in ("cancel", "reset", "revocation", "profile", "manual"):
        solution = client.get(base, headers=h()).json()
        run, _ = start_generation(
            client,
            h,
            solution,
            f"sections/{section_id}/generate",
            who="a-member" if reason == "revocation" else "a-owner",
        )
        version_before = solution["version"]

        def mutate(data, outline=False, reason=reason, run_id=run["id"]):
            if reason == "cancel":
                assert client.post(f"/api/v1/runs/{run_id}/cancel", headers=h()).status_code == 200
            elif reason == "reset":
                conversation_id = db.get(Solution, UUID(solution["id"])).conversation_id
                assert (
                    client.post(
                        f"/api/v1/conversations/{conversation_id}/reset",
                        headers=h(),
                        json={"confirm": True},
                    ).status_code
                    == 200
                )
            elif reason == "revocation":
                db.execute(
                    delete(CustomerAccess).where(CustomerAccess.user_id == users["a-member"][0].id)
                )
                db.commit()
            elif reason == "profile":
                profile = db.scalar(
                    select(RequirementProfile).where(
                        RequirementProfile.project_id == UUID(solution["project_id"])
                    )
                )
                profile.version += 1
                db.commit()
            else:
                edit = {
                    "version": version_before,
                    "request_id": str(uuid4()),
                    "section_id": section_id,
                    "content": {"type": "doc", "content": [{"type": "paragraph"}]},
                    "change_summary": "模型运行期间人工修订",
                }
                assert client.patch(base, headers=h(), json=edit).status_code == 200
            return section_result(data)

        monkeypatch.setattr(generation, "solution", mutate)
        db.rollback()
        solution_jobs.run_job(run["id"])
        db.expire_all()
        state = db.get(GenerationRun, UUID(run["id"]))
        assert state.status == ("cancelled" if reason in {"cancel", "reset"} else "failed")
        current = client.get(base, headers=h()).json()
        assert current["version"] == version_before + (reason == "manual")
        if reason == "revocation":
            db.add(
                CustomerAccess(
                    organization_id=orgs[0].id,
                    customer_id=customers[0].id,
                    user_id=users["a-member"][0].id,
                )
            )
            db.commit()


def test_expired_attempt_cannot_publish_or_fail_the_next_section(setup, db, monkeypatch):
    client, h, _, _, _, _, solution, _ = ready_solution(setup, db, monkeypatch)
    base = f"/api/v1/solutions/{solution['id']}"
    sections = solution["current"]["sections"]
    approved = client.post(
        base + "/outline/approve",
        headers=h(),
        json={
            "version": solution["version"],
            "request_id": str(uuid4()),
            "sections": [
                {"id": section["id"], "title": section["title"], "goal": "生成正文"}
                for section in sections
            ],
        },
    )
    assert approved.status_code == 202, approved.text
    run_id = approved.json()["id"]
    old_attempt_entered = False

    def race(data, outline=False):
        nonlocal old_attempt_entered
        if old_attempt_entered:
            return section_result(data, "（恢复尝试）")
        old_attempt_entered = True
        stale = db.get(GenerationRun, UUID(run_id))
        stale.lease_until = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        sent = []
        conversation_jobs.dispatch_once(sent.append)
        assert sent == [run_id]
        solution_jobs.run_job(run_id)
        raise RuntimeError("旧 attempt 在新 attempt 发布后失败")

    monkeypatch.setattr(generation, "solution", race)
    db.rollback()
    solution_jobs.run_job(run_id)
    db.expire_all()
    run = db.get(GenerationRun, UUID(run_id))
    current = client.get(base, headers=h()).json()
    assert run.status == "queued" and run.attempts == 0
    assert run.payload["remaining"] == [sections[1]["id"]]
    assert current["version"] == 3
    assert (
        "恢复尝试"
        in current["current"]["sections"][0]["content"]["content"][0]["content"][0]["text"]
    )
    assert current["current"]["sections"][1]["status"] == "pending"
