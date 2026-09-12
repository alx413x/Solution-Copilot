"""Version-bound quality reviews and private exports on the existing durable Run queue."""

import copy
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from solution_copilot.application import solutions
from solution_copilot.application.access import resolve_identity
from solution_copilot.application.conversation_jobs import checked_run
from solution_copilot.application.conversation_schemas import RunView
from solution_copilot.application.conversations import audit, event, run_access
from solution_copilot.application.documents import get_document
from solution_copilot.application.errors import AppError, missing
from solution_copilot.application.requirements import profile_for
from solution_copilot.application.workflows import active_check
from solution_copilot.config import get_settings
from solution_copilot.domain.models import (
    Clarification,
    Conversation,
    Customer,
    DocumentChunk,
    GenerationRun,
)
from solution_copilot.infrastructure import database, exports, generation
from solution_copilot.infrastructure import documents as storage


def start(session, identity, solution_id, data, kind):
    solution, project = solutions.access(session, identity, solution_id, True)
    request = data.model_dump(mode="json")
    prior = session.scalar(
        select(GenerationRun).where(
            GenerationRun.conversation_id == solution.conversation_id,
            GenerationRun.request_id == data.request_id,
        )
    )
    if prior:
        if (
            prior.payload.get("kind"),
            prior.payload.get("solution_id"),
            prior.payload.get("request"),
        ) != (kind, str(solution.id), request):
            raise AppError(409, "REQUEST_REUSED", "请求编号已用于其他操作。")
        return prior
    version = solutions.version(session, identity, solution_id, data.version)
    if kind == "export" and any(s["status"] == "pending" for s in version.sections):
        raise AppError(409, "INCOMPLETE_SOLUTION", "请先完成所有章节正文，再导出此版本。")
    if kind == "export" and any(exports.missing_references(s) for s in version.sections):
        raise AppError(409, "CITATION_MISSING", "正文含未登记的引用编号，请核对章节来源后再导出。")
    active_check(session, project.id)
    conversation = session.get(Conversation, solution.conversation_id)
    run = GenerationRun(
        id=uuid4(),
        organization_id=solution.organization_id,
        project_id=project.id,
        conversation_id=conversation.id,
        actor_user_id=identity.user_id,
        request_id=data.request_id,
        events=[],
        payload=dict(
            kind=kind, solution_id=str(solution.id), epoch=conversation.epoch, request=request
        ),
    )
    session.add(run)
    audit(session, identity, "solution." + kind, solution.id, version=data.version)
    session.commit()
    return run


def view(run):
    payload = run.payload
    result = payload.get("result", {}) if run.status == "succeeded" else {}
    return dict(
        run=RunView.model_validate(run),
        kind=payload["kind"],
        version=payload["request"]["version"],
        format=payload["request"].get("format"),
        issues=result.get("issues", []),
        coverage=result.get("coverage", []),
        coverage_percent=result.get("coverage_percent"),
        profile_version=result.get("profile_version"),
        download_url=f"/api/v1/exports/{run.id}/download"
        if run.status == "succeeded" and payload["kind"] == "export"
        else None,
    )


def listing(session, identity, solution_id, version):
    solutions.version(session, identity, solution_id, version)
    rows = session.scalars(
        select(GenerationRun)
        .where(
            GenerationRun.payload["solution_id"].astext == str(solution_id),
            GenerationRun.payload["kind"].astext.in_(["verify", "export"]),
            GenerationRun.payload["request"]["version"].as_integer() == version,
        )
        .order_by(GenerationRun.created_at.desc())
        .limit(50)
    )
    return [view(row) for row in rows]


def local_review(session, identity, project, sections, profile):
    issues = []

    def issue(rule, section, explanation, suggestion, severity="warning"):
        issues.append(
            dict(
                rule_id=rule,
                severity=severity,
                section_id=section,
                explanation=explanation,
                suggestion=suggestion,
            )
        )

    if session.scalar(
        select(Clarification.id)
        .where(
            Clarification.project_id == project.id,
            Clarification.importance == "required",
            Clarification.status != "answered",
        )
        .limit(1)
    ):
        issue(
            "required_clarification",
            None,
            "仍有必答澄清未回答。",
            "返回澄清页面补齐并确认需求。",
            "error",
        )
    # ponytail: exact customer names only; paraphrased private data needs human review.
    other_names = list(
        session.scalars(
            select(Customer.name).where(
                Customer.organization_id == identity.organization_id,
                Customer.id != project.customer_id,
            )
        )
    )
    requirements = (
        {i["id"]: i for i in profile.items if i["status"] == "confirmed"} if profile else {}
    )
    for section in sections:
        sid, text = section["id"], exports.plain(section["content"])
        if section["status"] == "pending":
            issue("incomplete_section", sid, "章节正文尚未生成。", "生成或补齐本章正文。", "error")
        if exports.missing_references(section):
            issue(
                "factual_citation",
                sid,
                "正文含未登记的引用编号。",
                "对照本章来源修正引用编号。",
                "error",
            )
        inspected = text + "\n" + "\n".join(c["quote"] for c in section["citations"])
        if any(name and name in inspected for name in other_names):
            issue(
                "customer_leak",
                sid,
                "正文疑似包含其他客户名称。",
                "核对本章并移除不应披露的信息。",
                "error",
            )
        if not section["citations"] and text.strip():
            issue(
                "factual_citation",
                sid,
                "本章没有来源引用。",
                "为事实主张补充可核实资料；推断应明确标注。",
            )
        if section["warnings"] or any(
            c["verification_status"] != "verified" for c in section["citations"]
        ):
            issue(
                "unverified_content",
                sid,
                "本章包含尚未人工核实的内容。",
                "逐项核对主张与来源摘录；模型检查不能代替人工确认。",
            )
        for citation in section["citations"]:
            if citation["source_type"] == "document":
                try:
                    doc = get_document(session, identity, UUID(citation["document_id"]))
                    chunk = session.get(DocumentChunk, UUID(citation["chunk_id"]))
                    valid = (
                        chunk is not None
                        and chunk.document_id == doc.id
                        and citation["quote"] in chunk.content
                        and doc.generation == citation.get("locator", {}).get("generation")
                        and doc.status == "ready"
                    ) and (
                        doc.scope == "organization"
                        or (
                            doc.customer_id == project.customer_id
                            and (doc.project_id is None or doc.project_id == project.id)
                        )
                    )
                except (AppError, ValueError, TypeError):
                    valid = False
            else:
                item = requirements.get(citation.get("locator", {}).get("requirement_id"))
                valid = bool(item and citation["quote"] in item["content"])
            if not valid:
                issue(
                    "citation_scope",
                    sid,
                    "引用当前不可用或不在本项目有效来源范围；历史摘录仍保留。",
                    "替换为当前可用来源并重新核实。",
                    "error",
                )
    return issues


def run_job(run_id):
    run_id, attempt = UUID(str(run_id)), None
    object_key = None
    try:
        with Session(database.get_engine()) as session:
            run, _, project = checked_run(session, run_id)
            if run.status != "queued":
                return
            identity = resolve_identity(session, run.actor_user_id, run.organization_id)
            solution, _ = solutions.access(
                session, identity, UUID(run.payload["solution_id"]), True
            )
            request, kind = run.payload["request"], run.payload["kind"]
            version = solutions.version(session, identity, solution.id, request["version"])
            sections, title = copy.deepcopy(version.sections), solution.title
            profile = profile_for(session, project)
            profile_version = profile.version if profile else None
            requirements = (
                [
                    dict(requirement_id=i["id"], content=i["content"])
                    for i in profile.items
                    if i["status"] == "confirmed"
                ]
                if profile
                else []
            )
            if kind == "verify":
                context = dict(
                    sections=[
                        dict(
                            id=s["id"],
                            title=s["title"],
                            text=exports.plain(s["content"]),
                            citations=s["citations"],
                        )
                        for s in sections
                    ],
                    confirmed_requirements=requirements,
                )
                import json

                if len(json.dumps(context, ensure_ascii=False)) > 100000:
                    raise AppError(
                        422, "REVIEW_LIMIT", "校验上下文超过 100000 字，请精简方案后重试。"
                    )
            run.status, run.attempts = "running", run.attempts + 1
            attempt = run.attempts
            run.lease_until = datetime.now(UTC) + timedelta(seconds=180)
            event(run, "node.started", node=kind, version=request["version"])
            organization_id, project_id = run.organization_id, project.id
            session.commit()
        if kind == "verify":
            output, info = generation.verify(context)
            ids = {s["id"] for s in sections}
            expected = {r["requirement_id"] for r in requirements}
            received = [r.requirement_id for r in output.coverage]
            if (
                len(received) != len(expected)
                or set(received) != expected
                or any(set(r.section_ids) - ids for r in output.coverage)
                or any(i.section_id is not None and i.section_id not in ids for i in output.issues)
            ):
                raise AppError(502, "INVALID_REVIEW", "模型校验定位不完整或无效，请重试。")
            result = output.model_dump(mode="json")
            result["coverage_percent"] = (
                round(100 * sum(bool(r.section_ids) for r in output.coverage) / len(expected), 1)
                if expected
                else None
            )
            result["profile_version"] = profile_version
        else:
            data = exports.render(title, request["version"], sections, request["format"])
            if len(data) > get_settings().upload_max_bytes:
                raise AppError(422, "EXPORT_LIMIT", "导出文件超过系统大小上限。")
            # Attempt-specific keys prevent a late retry from overwriting a published object.
            object_key = (
                f"{organization_id}/projects/{project_id}/exports/"
                f"{run_id}/{attempt}.{request['format']}"
            )
            storage.put_original(object_key, data, exports.MIMES[request["format"]])
            result = dict(
                storage_key=object_key, sha256=hashlib.sha256(data).hexdigest(), size=len(data)
            )
            info = {}
        with Session(database.get_engine()) as session:
            run, _, project = checked_run(session, run_id)
            if run.status != "running" or run.attempts != attempt:
                if object_key:
                    storage.delete_original(object_key)
                return
            identity = resolve_identity(session, run.actor_user_id, run.organization_id)
            solutions.access(session, identity, UUID(run.payload["solution_id"]), True)
            if kind == "verify":
                profile = profile_for(session, project)
                if (profile.version if profile else None) != profile_version:
                    raise AppError(409, "PROFILE_CHANGED", "检查期间需求已变化，请重新校验。")
                result["issues"] += local_review(session, identity, project, sections, profile)
                for item in result["coverage"]:
                    if not item["section_ids"]:
                        result["issues"].append(
                            dict(
                                rule_id="requirement_coverage",
                                severity="warning",
                                section_id=None,
                                explanation=f"已确认需求 {item['requirement_id']} 尚未被方案覆盖。",
                                suggestion="补充对应内容，再次校验。",
                            )
                        )
            run.payload = {**run.payload, "result": result}
            run.status, run.lease_until, run.model_info = "succeeded", None, info
            event(run, "node.completed", node=kind)
            event(run, "run.completed", version=request["version"])
            session.commit()
            object_key = None
    except Exception as exc:
        if object_key:
            try:
                storage.delete_original(object_key)
            except Exception:
                pass  # Private unreferenced objects are never exposed as downloads.
        with Session(database.get_engine()) as session:
            run = session.scalar(
                select(GenerationRun).where(GenerationRun.id == run_id).with_for_update()
            )
            if (
                run
                and run.status in {"queued", "running"}
                and (attempt is None or run.attempts == attempt)
            ):
                run.status, run.lease_until = "failed", None
                run.error_message = (
                    exc.message
                    if isinstance(exc, AppError)
                    else "校验或导出失败，请重试；保存的方案版本不受影响。"
                )
                event(run, "run.failed", message=run.error_message)
                session.commit()


def download(session, identity, export_id):
    run, _, _ = run_access(session, identity, export_id)
    if run.payload.get("kind") != "export" or run.status != "succeeded":
        raise missing()
    solution, _ = solutions.access(session, identity, UUID(run.payload["solution_id"]))
    result = run.payload["result"]
    try:
        data = storage.read_original(result["storage_key"])
        if hashlib.sha256(data).hexdigest() != result["sha256"]:
            raise ValueError("Export changed")
    except Exception:
        raise AppError(503, "EXPORT_UNAVAILABLE", "导出文件暂时不可下载，请重新导出。") from None
    audit(session, identity, "export.download", run.id, version=run.payload["request"]["version"])
    session.commit()
    format = run.payload["request"]["format"]
    extension = "md" if format == "markdown" else "docx"
    return (
        data,
        exports.MIMES[format],
        f"{solution.title}-v{run.payload['request']['version']}.{extension}",
    )
