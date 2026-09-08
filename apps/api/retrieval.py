from uuid import UUID

from fastapi import APIRouter
from pydantic import BaseModel
from solution_copilot.application.retrieval import SearchInput, search

from apps.api.auth import IdentityDep, SessionDep

router = APIRouter(prefix="/api/v1/retrieval", tags=["retrieval"])


class Evidence(BaseModel):
    chunk_id: UUID
    document_id: UUID
    title: str
    content: str
    page_number: int | None
    section_path: list[str]
    metadata: dict
    generation: int
    scope: str
    score: float
    ranks: dict[str, int]


class SearchResult(BaseModel):
    query: str
    profile: str
    items: list[Evidence]


@router.post("/search", response_model=SearchResult)
def retrieval(body: SearchInput, session: SessionDep, identity: IdentityDep):
    return search(session, identity, body)
