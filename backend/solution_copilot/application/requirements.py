import copy
import re
from datetime import UTC, datetime
from difflib import SequenceMatcher
from uuid import uuid4

from sqlalchemy import select

from solution_copilot.application.access import get_customer, get_project, require_write
from solution_copilot.application.customers import check_version, lock_customer
from solution_copilot.application.documents import get_document
from solution_copilot.application.errors import AppError, missing
from solution_copilot.application.requirement_schemas import REQUIRED
from solution_copilot.domain.models import (
    DocumentChunk,
    Project,
    RequirementExtraction,
    RequirementProfile,
)


def project_access(session, identity, project_id, write=False):
    project = get_project(session, identity, project_id)
    if write:
        require_write(identity)
        lock_customer(session, identity, project.customer_id)
        project = session.scalar(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update(of=Project)
            .execution_options(populate_existing=True)
        )
        if project.status == "archived":
            raise AppError(409, "ARCHIVED", "项目已归档，仅供查看。")
    return project


def profile_for(session, project, create=False):
    profile = session.scalar(
        select(RequirementProfile)
        .where(RequirementProfile.project_id == project.id)
        .execution_options(populate_existing=True)
    )
    if profile is None and create:
        profile = RequirementProfile(
            organization_id=project.organization_id,
            project_id=project.id,
            version=0,
            items=[],
            summary="",
            summary_edited=False,
        )
        session.add(profile)
        session.flush()
    return profile


def view(session, identity, project_id):
    project = project_access(session, identity, project_id)
    profile = profile_for(session, project)
    items = profile.items if profile else []
    present = {i["category"] for i in items if i["status"] in {"proposed", "confirmed"}}
    missing_categories = [c for c in REQUIRED if c not in present]
    return dict(
        project_id=project.id,
        version=profile.version if profile else 0,
        summary=profile.summary if profile else "",
        items=items,
        completeness_score=round(100 * (1 - len(missing_categories) / len(REQUIRED)), 2),
        missing_categories=missing_categories,
        confirmed_at=profile.confirmed_at if profile else None,
        writable=identity.role != "viewer"
        and project.status != "archived"
        and not get_customer(session, identity, project.customer_id).deleted_at,
        extraction=session.scalar(
            select(RequirementExtraction)
            .where(RequirementExtraction.project_id == project.id)
            .order_by(RequirementExtraction.created_at.desc())
            .limit(1)
        ),
    )


def source_material(session, identity, project, data):
    sources = []
    if data.text:
        sources.append(dict(source_id="text", type="user", title="本次输入", content=data.text))
    for document_id in dict.fromkeys(data.document_ids):
        doc = get_document(session, identity, document_id)
        if (
            doc.status == "disabled"
            or (doc.customer_id and doc.customer_id != project.customer_id)
            or (doc.project_id and doc.project_id != project.id)
        ):
            raise missing()
        chunks = list(
            session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == doc.id, DocumentChunk.generation == doc.generation
                )
                .order_by(DocumentChunk.ordinal)
            )
        )
        if not chunks:
            raise AppError(409, "NOT_PARSED", "所选资料尚未完成解析，请稍后重试。")
        for chunk in chunks:
            sources.append(
                dict(
                    source_id=str(chunk.id),
                    type="document",
                    title=doc.title,
                    document_id=str(doc.id),
                    generation=chunk.generation,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    section_path=chunk.section_path,
                    line_start=chunk.data.get("line_start"),
                    line_end=chunk.data.get("line_end"),
                )
            )
    # ponytail: one bounded model call; add batched extraction when >30k source chars is needed.
    if sum(len(s["content"]) for s in sources) > 30000 or len(sources) > 200:
        raise AppError(422, "SOURCE_LIMIT", "单次最多提取 30000 字、200 个片段，请减少所选资料。")
    return sources


def start(session, identity, project_id, data):
    project = project_access(session, identity, project_id, True)
    active = session.scalar(
        select(RequirementExtraction).where(
            RequirementExtraction.project_id == project_id,
            RequirementExtraction.status.in_(["queued", "running"]),
        )
    )
    if active:
        raise AppError(409, "EXTRACTION_ACTIVE", "已有提取任务，请等待完成或取消。")
    sources = source_material(session, identity, project, data)
    profile = profile_for(session, project, True)
    existing = [
        {k: item[k] for k in ("id", "category", "title", "content", "priority", "status")}
        for item in profile.items
    ]
    if sum(len(i["content"]) + len(i["title"]) for i in existing) > 30000:
        raise AppError(422, "PROFILE_LIMIT", "现有档案超过单次模型输入上限，请拆分项目。")
    row = RequirementExtraction(
        organization_id=identity.organization_id,
        project_id=project_id,
        actor_user_id=identity.user_id,
        payload={"sources": sources, "base_version": profile.version, "existing": existing},
    )
    session.add(row)
    session.commit()
    return row


def cancel(session, identity, project_id, extraction_id):
    project_access(session, identity, project_id, True)
    row = session.scalar(
        select(RequirementExtraction)
        .where(
            RequirementExtraction.project_id == project_id,
            RequirementExtraction.id == extraction_id,
        )
        .with_for_update()
    )
    if row is None:
        raise missing()
    if row.status in {"queued", "running"}:
        row.status, row.lease_until = "cancelled", None
    session.commit()
    return row


def norm(value):
    return re.sub(r"\W+", "", value.casefold())


def merge(profile, output, sources):
    items = copy.deepcopy(profile.items)
    source_map = {s["source_id"]: s for s in sources}
    for candidate in output.items:
        src = source_map.get(candidate.source_id)
        if not src or candidate.quote not in src["content"]:
            raise AppError(502, "INVALID_SOURCE", "模型引用无法在来源中找到，档案未修改，请重试。")
        evidence = {k: v for k, v in src.items() if k != "content"}
        evidence["quote"] = candidate.quote
        related = next((i for i in items if i["id"] == str(candidate.related_id)), None)
        if candidate.related_id and (not related or related["category"] != candidate.category):
            raise AppError(502, "INVALID_RELATION", "模型返回无效的需求关联，请重试。")
        exact = next(
            (
                i
                for i in items
                if i["category"] == candidate.category
                and norm(i["content"]) == norm(candidate.content)
            ),
            None,
        )
        target = exact or related
        if not target:
            target = next(
                (
                    i
                    for i in items
                    if i["category"] == candidate.category
                    and (
                        norm(i["title"]) == norm(candidate.title)
                        or SequenceMatcher(
                            None, norm(i["content"]), norm(candidate.content)
                        ).ratio()
                        >= 0.8
                    )
                ),
                None,
            )
        # Same digits and polarity are required even when the model claims equivalence.
        equivalent = target and (
            exact
            or (
                candidate.relation == "duplicate"
                and re.findall(r"\d+(?:\.\d+)?", target["content"])
                == re.findall(r"\d+(?:\.\d+)?", candidate.content)
                and bool(re.search("不|无|禁止|不得|不能", target["content"]))
                == bool(re.search("不|无|禁止|不得|不能", candidate.content))
            )
        )
        if equivalent:
            if evidence not in target["sources"]:
                target["sources"].append(evidence)
            continue
        conflicts = [target["id"]] if target and target["status"] != "rejected" else []
        items.append(
            dict(
                id=str(uuid4()),
                **candidate.model_dump(
                    include={"category", "title", "content", "priority", "confidence"}
                ),
                status="conflicted" if conflicts else "proposed",
                sources=[evidence],
                edited=False,
                conflicts_with=conflicts,
            )
        )
    if len(items) > 200:
        raise AppError(422, "ITEM_LIMIT", "需求档案最多 200 项，请拆分项目。")
    profile.items = items
    if not profile.summary_edited and not profile.confirmed_at:
        profile.summary = output.summary
    profile.version += 1
    profile.confirmed_at = profile.confirmed_by = None


def edit(session, identity, project_id, data, confirm=False):
    project = project_access(session, identity, project_id, True)
    profile = profile_for(session, project, True)
    check_version(profile, data.version)
    items = copy.deepcopy(profile.items)
    if confirm:
        active = [i for i in items if i["status"] != "rejected"]
        if not active or any(i["status"] == "conflicted" for i in active):
            raise AppError(409, "UNRESOLVED", "请先添加需求并解决所有冲突。")
        for item in active:
            item["status"] = "confirmed"
        profile.confirmed_at, profile.confirmed_by = datetime.now(UTC), identity.user_id
    else:
        target = next((i for i in items if i["id"] == str(data.item_id)), None)
        if data.item_id and not target:
            raise missing()
        if data.resolve_with:
            if not target or target["status"] != "conflicted":
                raise AppError(409, "NOT_CONFLICT", "该项没有待解决冲突。")
            if data.resolve_with == "replace":
                for old in items:
                    if old["id"] in target["conflicts_with"]:
                        old["status"] = "rejected"
                target["status"] = "confirmed"
            else:
                target["status"] = "rejected"
            target["edited"] = True
        elif data.status:
            if not target or target["status"] == "conflicted":
                raise AppError(409, "UNRESOLVED", "冲突项请使用保留原项或采用新项操作。")
            target["status"] = data.status
        if data.item:
            if target:
                target.update(data.item.model_dump())
                target["edited"] = True
                target["confidence"] = None
                if target["status"] != "conflicted":
                    target["status"] = "proposed"
            else:
                items.append(
                    dict(
                        id=str(uuid4()),
                        **data.item.model_dump(),
                        status="proposed",
                        confidence=None,
                        sources=[],
                        edited=True,
                        conflicts_with=[],
                    )
                )
        if data.summary is not None:
            profile.summary, profile.summary_edited = data.summary, True
        profile.confirmed_at = profile.confirmed_by = None
    if len(items) > 200:
        raise AppError(422, "ITEM_LIMIT", "需求档案最多 200 项。")
    profile.items = items
    profile.version += 1
    session.commit()
    return view(session, identity, project_id)
