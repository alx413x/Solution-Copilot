"""Bounded model and editor input; never accept HTML or client-supplied evidence."""

import json
import re
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from solution_copilot.application.conversation_schemas import RunView
from solution_copilot.application.schemas import Input


class SourceClaim(Input):
    source_id: str = Field(min_length=1, max_length=80)
    quote: str = Field(min_length=1, max_length=2000)


class Paragraph(Input):
    text: str = Field(min_length=1, max_length=3000)
    sources: list[SourceClaim] = Field(default_factory=list, max_length=5)


class SectionOutput(Input):
    paragraphs: list[Paragraph] = Field(min_length=1, max_length=20)


class OutlineIdea(Paragraph):
    title: str = Field(min_length=1, max_length=160)


class OutlineOutput(Input):
    sections: list[OutlineIdea] = Field(min_length=1, max_length=20)


class CreateSolution(Input):
    workflow_run_id: UUID
    title: str = Field(default="项目解决方案", min_length=1, max_length=200)


class GenerateInput(Input):
    version: int = Field(ge=1)
    request_id: UUID
    instruction: str = Field(default="", max_length=2000)


class OutlineEntry(Input):
    id: str = Field(pattern=r"^(?:section-[0-9]{2}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$")
    title: str = Field(min_length=1, max_length=160)
    goal: str = Field(default="", max_length=3000)


class ApproveOutline(GenerateInput):
    sections: list[OutlineEntry] = Field(min_length=1, max_length=20)

    @field_validator("sections")
    @classmethod
    def unique(cls, sections):
        if len({s.id for s in sections}) != len(sections):
            raise ValueError("Duplicate section ID")
        return sections


def validate_document(doc):
    count = 0

    def visit(node, depth=0):
        nonlocal count
        count += 1
        if depth > 12 or count > 2000 or not isinstance(node, dict):
            raise ValueError("Invalid document size")
        kind = node.get("type")
        allowed = {
            "doc",
            "paragraph",
            "heading",
            "text",
            "bulletList",
            "orderedList",
            "listItem",
            "blockquote",
            "codeBlock",
            "hardBreak",
            "horizontalRule",
            "table",
            "tableRow",
            "tableCell",
            "tableHeader",
        }
        if (
            not isinstance(kind, str)
            or kind not in allowed
            or set(node) - {"type", "content", "text", "marks", "attrs"}
        ):
            raise ValueError("Unsupported document node")
        attrs = node.get("attrs", {})
        expected = {
            "heading": {"level"},
            "orderedList": {"start", "type"},
            "codeBlock": {"language"},
            "tableCell": {"colspan", "rowspan", "colwidth", "align"},
            "tableHeader": {"colspan", "rowspan", "colwidth", "align"},
        }
        if not isinstance(attrs, dict) or set(attrs) - expected.get(kind, set()):
            raise ValueError("Unsupported document attributes")
        if kind == "heading" and (
            type(attrs.get("level")) is not int or attrs.get("level") not in (2, 3)
        ):
            raise ValueError("Invalid heading")
        if kind == "orderedList" and (
            type(attrs.get("start", 1)) is not int or not 1 <= attrs.get("start", 1) <= 10000
        ):
            raise ValueError("Invalid list start")
        if kind == "orderedList" and attrs.get("type") not in (None, "1", "a", "A", "i", "I"):
            raise ValueError("Invalid list type")
        if kind == "codeBlock" and attrs.get("language") is not None:
            language = attrs["language"]
            if not isinstance(language, str) or not re.fullmatch(r"[\w+-]{1,40}", language):
                raise ValueError("Invalid code language")
        if kind in {"tableCell", "tableHeader"} and (
            type(attrs.get("colspan", 1)) is not int
            or attrs.get("colspan", 1) != 1
            or type(attrs.get("rowspan", 1)) is not int
            or attrs.get("rowspan", 1) != 1
            or attrs.get("colwidth") is not None
            or attrs.get("align") is not None
        ):
            raise ValueError(
                "Only simple tables without merged cells or custom widths are supported"
            )
        marks = node.get("marks", [])
        if not isinstance(marks, list) or any(
            m not in ({"type": "bold"}, {"type": "italic"}, {"type": "strike"}, {"type": "code"})
            for m in marks
        ):
            raise ValueError("Unsupported mark")
        if kind == "text":
            if not isinstance(node.get("text"), str) or not node["text"] or "content" in node:
                raise ValueError("Invalid text")
        elif "text" in node or marks:
            raise ValueError("Only text can carry marks")
        children = node.get("content", [])
        if not isinstance(children, list):
            raise ValueError("Invalid children")
        permitted = {
            "doc": {
                "paragraph",
                "heading",
                "bulletList",
                "orderedList",
                "blockquote",
                "codeBlock",
                "horizontalRule",
                "table",
            },
            "table": {"tableRow"},
            "tableRow": {"tableCell", "tableHeader"},
            "tableCell": {"paragraph"},
            "tableHeader": {"paragraph"},
            "paragraph": {"text", "hardBreak"},
            "heading": {"text", "hardBreak"},
            "codeBlock": {"text"},
            "bulletList": {"listItem"},
            "orderedList": {"listItem"},
            "listItem": {"paragraph", "bulletList", "orderedList"},
            "blockquote": {"paragraph", "heading", "bulletList", "orderedList", "codeBlock"},
        }
        for child in children:
            if (
                not isinstance(child, dict)
                or not isinstance(child.get("type"), str)
                or child.get("type") not in permitted.get(kind, set())
            ):
                raise ValueError("Invalid nesting")
            visit(child, depth + 1)
        if kind in {"doc", "bulletList", "orderedList", "listItem", "blockquote"} and not children:
            raise ValueError("Container cannot be empty")
        if kind in {"table", "tableRow", "tableCell", "tableHeader"} and not children:
            raise ValueError("Table elements cannot be empty")
        if kind == "table" and (
            len(children) > 50
            or len(children[0]["content"]) > 20
            or len({len(c["content"]) for c in children}) != 1
        ):
            raise ValueError("Expected rectangular table with at most 50 rows and 20 columns")
        if kind == "listItem" and children[0]["type"] != "paragraph":
            raise ValueError("List item must begin with paragraph")

    if not isinstance(doc, dict) or doc.get("type") != "doc":
        raise ValueError("Expected document")
    visit(doc)
    if len(json.dumps(doc, ensure_ascii=False)) > 100000:
        raise ValueError("Section exceeds 100000 characters")
    return doc


class EditSection(Input):
    version: int = Field(ge=1)
    request_id: UUID
    section_id: str = Field(min_length=1, max_length=80)
    content: dict
    change_summary: str = Field(default="人工编辑", min_length=1, max_length=240)

    @field_validator("content")
    @classmethod
    def valid_content(cls, value):
        return validate_document(value)


class CitationView(BaseModel):
    id: str
    claim_text: str
    quote: str
    source_type: Literal["document", "user_input"]
    source_id: str
    title: str
    document_id: str | None = None
    chunk_id: str | None = None
    locator: dict = Field(default_factory=dict)
    verification_status: Literal["partial", "unverified"]


class SectionView(BaseModel):
    id: str
    title: str
    goal: str
    status: str
    content: dict
    citations: list[CitationView]
    warnings: list[str]


class VersionView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    sections: list[SectionView]
    created_at: datetime
    created_by: UUID
    change_summary: str
    generation_run_id: UUID | None


class VersionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    created_at: datetime
    change_summary: str


class SolutionView(BaseModel):
    id: UUID
    project_id: UUID
    title: str
    status: str
    version: int
    current: VersionView
    writable: bool
    run: RunView | None
