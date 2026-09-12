from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from solution_copilot.application.conversation_schemas import RunView
from solution_copilot.application.schemas import Input


class VerifyInput(Input):
    version: int = Field(ge=1, le=200)
    request_id: UUID


class ExportInput(VerifyInput):
    format: Literal["markdown", "docx"]


class QualityIssue(Input):
    rule_id: Literal[
        "requirement_coverage",
        "required_clarification",
        "contradiction",
        "factual_citation",
        "citation_scope",
        "customer_leak",
        "unsupported_promise",
        "acceptance_metric",
        "incomplete_section",
        "unverified_content",
    ]
    severity: Literal["error", "warning", "info"]
    section_id: str | None = Field(default=None, max_length=80)
    explanation: str = Field(min_length=1, max_length=1000)
    suggestion: str = Field(min_length=1, max_length=1000)


class Coverage(Input):
    requirement_id: str = Field(max_length=80)
    section_ids: list[str] = Field(max_length=20)


class QualityOutput(Input):
    issues: list[QualityIssue] = Field(max_length=100)
    coverage: list[Coverage] = Field(max_length=200)


class DeliveryView(BaseModel):
    run: RunView
    kind: Literal["verify", "export"]
    version: int
    format: Literal["markdown", "docx"] | None = None
    issues: list[QualityIssue] = []
    coverage: list[Coverage] = []
    coverage_percent: float | None = None
    profile_version: int | None = None
    download_url: str | None = None
