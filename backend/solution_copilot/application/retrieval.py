"""Both candidate lists use the same authorized SQL scope, then reciprocal-rank fusion."""

import math
import re
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from typing import Literal
from uuid import UUID

import jieba
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_, select

from solution_copilot.application.access import get_customer, get_project
from solution_copilot.application.documents import document_scope
from solution_copilot.application.errors import AppError
from solution_copilot.domain.models import Document, DocumentChunk
from solution_copilot.infrastructure import embeddings


def words(value):
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return [word for word in jieba.cut_for_search(normalized) if re.fullmatch(r"\w+", word)]


class SearchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=500)
    customer_id: UUID | None = None
    project_id: UUID | None = None
    scopes: list[Literal["organization", "customer", "project"]] = Field(
        default_factory=lambda: ["organization", "customer", "project"], max_length=3
    )
    mime_types: list[str] = Field(default_factory=list, max_length=4)
    tags: list[str] = Field(default_factory=list, max_length=10)
    top_k: int = Field(8, ge=1, le=30)
    candidates: int = Field(20, ge=1, le=100)
    document_share: float = Field(0.4, gt=0, le=1)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("Query cannot be blank")
        return value


def search(session, identity, request):
    customer_id = request.customer_id
    if request.project_id:
        project = get_project(session, identity, request.project_id)
        if customer_id and customer_id != project.customer_id:
            raise AppError(422, "INVALID_SCOPE", "项目与客户不匹配。")
        customer_id = project.customer_id
    if customer_id:
        get_customer(session, identity, customer_id)
    context = [Document.scope == "organization"]
    if customer_id:
        context.append(and_(Document.scope == "customer", Document.customer_id == customer_id))
    if request.project_id:
        context.append(and_(Document.scope == "project", Document.project_id == request.project_id))
    filters = [
        *document_scope(identity),
        or_(*context),
        Document.scope.in_(request.scopes),
        Document.status != "disabled",
        DocumentChunk.generation == Document.generation,
        DocumentChunk.embedding_profile == embeddings.PROFILE,
    ]
    if request.mime_types:
        filters.append(Document.mime_type.in_(request.mime_types))
    if request.tags:
        filters.append(Document.data["tags"].contains(request.tags))
    # ponytail: exact search on the authorized MVP corpus; evaluate HNSW at measured scale.
    eligible = (
        select(DocumentChunk.id, DocumentChunk.embedding, DocumentChunk.search_vector)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(*filters)
        .cte("authorized_chunks")
        .prefix_with("MATERIALIZED")
    )
    query_terms = words(request.query)
    if not query_terms or not request.scopes:
        return {"query": request.query, "items": [], "profile": embeddings.PROFILE}
    vector = embeddings.embed_query(request.query)
    semantic = list(
        session.scalars(
            select(eligible.c.id)
            .order_by(eligible.c.embedding.cosine_distance(vector), eligible.c.id)
            .limit(request.candidates)
        )
    )
    tsquery = func.to_tsquery("simple", " | ".join(dict.fromkeys(query_terms)))
    keyword = list(
        session.scalars(
            select(eligible.c.id)
            .where(eligible.c.search_vector.op("@@")(tsquery))
            .order_by(func.ts_rank_cd(eligible.c.search_vector, tsquery).desc(), eligible.c.id)
            .limit(request.candidates)
        )
    )
    scores, ranks = defaultdict(float), defaultdict(dict)
    for name, candidates in [("semantic", semantic), ("keyword", keyword)]:
        for rank, chunk_id in enumerate(candidates, 1):
            scores[chunk_id] += 1 / (60 + rank)
            ranks[chunk_id][name] = rank
    rows = session.execute(
        select(DocumentChunk, Document)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.id.in_(scores), *filters)
    ).all()
    by_id = {chunk.id: (chunk, doc) for chunk, doc in rows}
    items, seen, counts = [], set(), Counter()
    cap = max(1, math.floor(request.top_k * request.document_share))
    for chunk_id in sorted(scores, key=lambda key: (-scores[key], str(key))):
        if chunk_id not in by_id:
            continue
        chunk, doc = by_id[chunk_id]
        normalized = re.sub(r"\s+", "", unicodedata.normalize("NFKC", chunk.content)).casefold()
        if counts[doc.id] >= cap or any(
            SequenceMatcher(None, normalized, previous).ratio() >= 0.92 for previous in seen
        ):
            continue
        seen.add(normalized)
        counts[doc.id] += 1
        items.append(
            {
                "chunk_id": chunk.id,
                "document_id": doc.id,
                "title": doc.title,
                "content": chunk.content,
                "page_number": chunk.page_number,
                "section_path": chunk.section_path,
                "metadata": chunk.data,
                "generation": chunk.generation,
                "scope": doc.scope,
                "score": scores[chunk_id],
                "ranks": ranks[chunk_id],
            }
        )
        if len(items) == request.top_k:
            break
    return {"query": request.query, "items": items, "profile": embeddings.PROFILE}
