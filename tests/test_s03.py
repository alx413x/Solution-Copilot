"""Real pgvector/FTS SQL with deterministic vectors; real model evaluation is separate."""

from uuid import uuid4

import pytest
from solution_copilot.application.retrieval import words
from solution_copilot.domain.models import CustomerAccess, Document, DocumentChunk
from solution_copilot.infrastructure import embeddings
from sqlalchemy import delete, func, select
from test_s01 import db as db
from test_s01 import setup as setup


def add_document(db, org, text, scope="organization", customer=None, project=None, vector=None):
    doc = Document(
        id=uuid4(),
        organization_id=org.id,
        scope=scope,
        customer_id=customer,
        project_id=project,
        title=text[:30],
        mime_type="text/plain",
        sha256=uuid4().hex,
        storage_key=uuid4().hex,
        status="ready",
        generation=1,
        data={"embedding_profile": embeddings.PROFILE, "tags": ["产品"]},
    )
    db.add(doc)
    db.flush()
    chunk = DocumentChunk(
        document_id=doc.id,
        organization_id=org.id,
        ordinal=0,
        generation=1,
        content=text,
        token_count=10,
        section_path=["安全"],
        data={"line_start": 1},
        embedding=vector or [1.0] + [0.0] * 511,
        embedding_profile=embeddings.PROFILE,
        search_vector=func.to_tsvector("simple", " ".join(words(text))),
    )
    db.add(chunk)
    db.commit()
    return doc


def test_authorized_candidates_context_and_revocation(setup, db, monkeypatch):
    client, h, customers, users, orgs = setup
    monkeypatch.setattr(embeddings, "embed_query", lambda _: [1.0] + [0.0] * 511)
    org = add_document(db, orgs[0], "组织单点登录支持统一身份认证")
    own = add_document(db, orgs[0], "客户数据需要权限隔离", "customer", customers[0].id)
    for number in range(22):
        add_document(db, orgs[0], f"客户秘密单点登录{number}", "customer", customers[1].id)
    add_document(db, orgs[1], "外部组织单点登录秘密")

    def search(**fields):
        response = client.post(
            "/api/v1/retrieval/search",
            headers=h("a-member"),
            json={"query": "单点登录", "document_share": 1, **fields},
        )
        assert response.status_code == 200, response.text
        return response.json()["items"]

    assert {x["document_id"] for x in search()} == {str(org.id)}
    results = search(customer_id=str(customers[0].id))
    assert {x["document_id"] for x in results} == {str(org.id), str(own.id)}
    assert "keyword" in next(x for x in results if x["document_id"] == str(org.id))["ranks"]
    assert not search(tags=["不存在"])
    assert not search(mime_types=["application/pdf"])
    assert (
        client.post(
            "/api/v1/retrieval/search",
            headers=h("a-member"),
            json={"query": "秘密", "customer_id": str(customers[1].id)},
        ).status_code
        == 404
    )
    db.execute(delete(CustomerAccess).where(CustomerAccess.user_id == users["a-member"][0].id))
    db.commit()
    assert (
        client.post(
            "/api/v1/retrieval/search",
            headers=h("a-member"),
            json={"query": "隔离", "customer_id": str(customers[0].id)},
        ).status_code
        == 404
    )
    assert client.post(f"/api/v1/documents/{org.id}/disable", headers=h()).status_code == 200
    assert not search()


def test_profile_generation_errors_and_dedup(setup, db, monkeypatch):
    client, h, _, _, orgs = setup
    monkeypatch.setattr(embeddings, "embed_query", lambda _: [1.0] + [0.0] * 511)
    doc = add_document(db, orgs[0], "备份恢复支持异地容灾")
    add_document(db, orgs[0], "备份恢复支持异地容灾")
    obsolete = add_document(db, orgs[0], "旧模型资料")
    chunk = db.scalar(select(DocumentChunk).where(DocumentChunk.document_id == obsolete.id))
    chunk.embedding_profile = "obsolete"
    doc.status = "failed"  # Failed rebuild leaves the previous complete generation readable.
    db.commit()
    response = client.post("/api/v1/retrieval/search", headers=h(), json={"query": "备份恢复"})
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1 and items[0]["content"] == "备份恢复支持异地容灾"
    for body in [
        {"query": " "},
        {"query": "查询", "organization_id": str(orgs[1].id)},
        {"query": "查询", "scopes": ["public"]},
    ]:
        assert client.post("/api/v1/retrieval/search", headers=h(), json=body).status_code == 422
    with pytest.raises(Exception):
        embeddings.checked([[float("nan")] * 512], 1)
