"""One model call per durable step; completed sections survive later failures."""

import copy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from solution_copilot.application import retrieval, solutions
from solution_copilot.application.access import resolve_identity
from solution_copilot.application.conversation_jobs import checked_run
from solution_copilot.application.conversations import event
from solution_copilot.application.errors import AppError
from solution_copilot.application.workflows import ready_profile, validate_snapshot
from solution_copilot.domain.models import GenerationRun
from solution_copilot.infrastructure import database, generation


def sources_for(session, identity, project, profile, query):
    requirements = [i for i in profile.items if i["status"] == "confirmed"]
    if sum(len(i["content"]) for i in requirements) > 30000:
        raise AppError(422, "PROFILE_LIMIT", "已确认需求超过 30000 字，请整理后生成。")
    # ponytail: lexical ranking of <=200 requirement items; use measured retrieval later.
    terms = set(retrieval.words(query))
    requirements.sort(
        key=lambda i: len(terms & set(retrieval.words(i["title"] + i["content"]))), reverse=True
    )
    sources = [
        dict(
            source_id="requirement:" + i["id"],
            source_type="user_input",
            title=i["title"],
            content=i["content"],
            locator={"requirement_id": i["id"], "profile_version": profile.version},
        )
        for i in requirements[:12]
    ]
    hits = retrieval.search(
        session, identity, retrieval.SearchInput(query=query[:500], project_id=project.id)
    )["items"]
    for hit in hits:
        sources.append(
            dict(
                source_id=str(hit["chunk_id"]),
                source_type="document",
                title=hit["title"],
                content=hit["content"],
                document_id=str(hit["document_id"]),
                chunk_id=str(hit["chunk_id"]),
                generation=hit["generation"],
                locator={
                    "page_number": hit["page_number"],
                    "section_path": hit["section_path"],
                    "generation": hit["generation"],
                },
            )
        )
    return sources


def make_content(paragraphs, sources):
    by_id = {s["source_id"]: s for s in sources}
    citations, content = [], []
    for paragraph in paragraphs:
        ids = []
        for claim in paragraph.sources:
            source = by_id.get(claim.source_id)
            if source is None or claim.quote not in source["content"]:
                raise AppError(502, "INVALID_CITATION", "模型引用不在本次授权资料中，结果未写入。")
            number = str(len(citations) + 1)
            citations.append(
                dict(
                    id=number,
                    claim_text=paragraph.text,
                    quote=claim.quote,
                    source_type=source["source_type"],
                    source_id=source["source_id"],
                    title=source["title"],
                    document_id=source.get("document_id"),
                    chunk_id=source.get("chunk_id"),
                    locator=source["locator"],
                    verification_status="partial",
                )
            )
            ids.append(number)
        suffix = " " + "".join(f"[{i}]" for i in ids) if ids else " [待进一步核实]"
        content.append(
            dict(type="paragraph", content=[dict(type="text", text=paragraph.text + suffix)])
        )
    return {"type": "doc", "content": content}, citations


def run_job(run_id):
    run_id, attempt, step = UUID(str(run_id)), None, None
    try:
        with Session(database.get_engine()) as session:
            run, conversation, project = checked_run(session, run_id)
            if run.status != "queued":
                return
            identity = resolve_identity(session, run.actor_user_id, run.organization_id)
            solution, _ = solutions.access(
                session, identity, UUID(run.payload["solution_id"]), True
            )
            solutions.check_version(solution, run.payload["base_version"])
            profile, ready = ready_profile(session, project)
            if not ready or profile.version != run.payload["profile_version"]:
                raise AppError(409, "PROFILE_CHANGED", "需求档案已变化，请重新发起生成。")
            sections = copy.deepcopy(solutions.current(session, solution).sections)
            step = run.payload["remaining"][0]
            base_version = solution.version
            target = next((s for s in sections if s["id"] == step), None)
            query = (
                (target["title"] + " " + target["goal"])
                if target
                else solution.title + " " + profile.summary
            )
            sources = sources_for(session, identity, project, profile, query)
            snapshot = dict(
                profile_version=profile.version,
                evidence=[
                    dict(chunk_id=s["chunk_id"], generation=s["generation"])
                    for s in sources
                    if s["source_type"] == "document"
                ],
            )
            data = dict(
                title=solution.title,
                section=target and {k: target[k] for k in ("id", "title", "goal")},
                outline=[{k: s[k] for k in ("id", "title", "goal")} for s in sections],
                instruction=run.payload["request"]["instruction"],
                sources=sources,
            )
            run.status, run.attempts = "running", run.attempts + 1
            attempt = run.attempts
            run.lease_until = datetime.now(UTC) + timedelta(seconds=180)
            event(run, "node.started", node=step, attempt=attempt)
            session.commit()
        output, info = generation.solution(data, outline=step == "outline")
        with Session(database.get_engine()) as session:
            run, conversation, project = checked_run(session, run_id)
            if (
                run.status != "running"
                or run.attempts != attempt
                or run.payload["base_version"] != base_version
                or run.payload["remaining"][:1] != [step]
            ):
                return
            identity = resolve_identity(session, run.actor_user_id, run.organization_id)
            solution, _ = solutions.access(
                session, identity, UUID(run.payload["solution_id"]), True
            )
            solutions.check_version(solution, run.payload["base_version"])
            profile, ready = ready_profile(session, project)
            if not ready:
                raise AppError(409, "PROFILE_CHANGED", "请重新确认需求。")
            validate_snapshot(session, identity, project, snapshot, profile)
            if step == "outline":
                sections = []
                for idea in output.sections:
                    section = solutions.empty_section(
                        dict(id=str(uuid4()), title=idea.title, goal=idea.text)
                    )
                    _, section["citations"] = make_content([idea], sources)
                    section["warnings"] = ["大纲建议待人工确认，正文尚未生成。"]
                    sections.append(section)
                solution.profile_version = profile.version
            else:
                target = next(s for s in sections if s["id"] == step)
                target["content"], target["citations"] = make_content(output.paragraphs, sources)
                target["status"], target["warnings"] = (
                    "draft",
                    ["AI 草稿待核实；引用仅校验来源摘录匹配，不代表主张已被证实。"],
                )
            version = solutions.append_version(
                session,
                solution,
                identity,
                sections,
                "生成大纲" if step == "outline" else "生成章节：" + target["title"],
                run.id,
            )
            remaining = run.payload["remaining"][1:]
            run.payload = {**run.payload, "remaining": remaining, "base_version": solution.version}
            run.model_info = {**run.model_info, step: info}
            run.status, run.lease_until = ("queued" if remaining else "succeeded"), None
            if remaining:
                run.attempts = 0  # Retry budget belongs to the next step, not previous successes.
            solution.status = (
                "outlining" if step == "outline" else "generating" if remaining else "draft"
            )
            event(
                run,
                "section.completed",
                section_id=step,
                version=version.version,
                remaining=len(remaining),
            )
            event(run, "node.completed", node=step)
            if not remaining:
                event(run, "run.completed", solution_id=str(solution.id), version=solution.version)
            session.commit()
    except Exception as exc:
        with Session(database.get_engine()) as session:
            run = session.scalar(
                select(GenerationRun).where(GenerationRun.id == run_id).with_for_update()
            )
            if (
                run
                and run.status in {"queued", "running"}
                and (
                    attempt is None
                    or (run.attempts == attempt and run.payload["remaining"][:1] == [step])
                )
            ):
                run.status, run.lease_until = "failed", None
                run.error_message = (
                    exc.message
                    if isinstance(exc, AppError)
                    else "章节生成失败；已保存版本保留，请重试未完成章节。"
                )
                event(run, "run.failed", message=run.error_message)
                session.commit()
