"""Project-scoped immutable versions. Model calls belong to solution_jobs."""

import copy
from uuid import uuid4

from sqlalchemy import select

from solution_copilot.application.conversation_schemas import RunView
from solution_copilot.application.conversations import audit, run_access
from solution_copilot.application.errors import AppError, missing
from solution_copilot.application.requirements import project_access
from solution_copilot.application.requirements import view as profile_view
from solution_copilot.application.workflows import active_check, ready_profile, validate_snapshot
from solution_copilot.domain.models import GenerationRun, Solution, SolutionVersion


def access(session, identity, solution_id, write=False):
    row = session.get(Solution, solution_id)
    if row is None or row.organization_id != identity.organization_id:
        raise missing()
    project = project_access(session, identity, row.project_id, write)
    session.refresh(row)
    return row, project


def current(session, row):
    return session.scalar(
        select(SolutionVersion).where(
            SolutionVersion.solution_id == row.id, SolutionVersion.version == row.version
        )
    )


def check_version(row, version):
    if row.version != version:
        raise AppError(409, "SOLUTION_CHANGED", "方案已有新版本；请保留当前修改并刷新核对。")
    if row.version >= 200:
        raise AppError(422, "VERSION_LIMIT", "此方案已达到 200 个版本上限。")


def empty_section(section):
    return dict(
        id=section["id"],
        title=section["title"],
        goal=section.get("goal", ""),
        status="pending",
        content={"type": "doc", "content": [{"type": "paragraph"}]},
        citations=[],
        warnings=["待生成正文"],
    )


def append_version(session, row, identity, sections, summary, run_id=None, request=None):
    row.version += 1
    version = SolutionVersion(
        organization_id=row.organization_id,
        solution_id=row.id,
        version=row.version,
        sections=sections,
        created_by=identity.user_id,
        change_summary=summary,
        generation_run_id=run_id,
        request_id=request.request_id if request else None,
        request_data=request.model_dump(mode="json") if request else {},
    )
    session.add(version)
    session.flush()
    return version


def create(session, identity, project_id, data):
    project = project_access(session, identity, project_id, True)
    run, conversation, run_project = run_access(session, identity, data.workflow_run_id)
    if (
        run_project.id != project.id
        or run.status != "succeeded"
        or not run.workflow
        or run.workflow["stage"] != "ready_for_generation"
    ):
        raise AppError(409, "WORKFLOW_REQUIRED", "请先完成本项目的需求与大纲编排。")
    existing = session.scalar(select(Solution).where(Solution.project_id == project.id))
    if existing:
        if existing.workflow_run_id != run.id or existing.title != data.title:
            raise AppError(409, "SOLUTION_EXISTS", "项目已有方案，请继续编辑已有方案。")
        return existing
    if conversation.epoch != run.payload["epoch"]:
        raise AppError(409, "CONTEXT_RESET", "编排所属会话已重置，请重新编排。")
    profile, ready = ready_profile(session, project)
    if not ready:
        raise AppError(409, "REQUIREMENTS_UNCONFIRMED", "请先确认完整需求档案。")
    validate_snapshot(session, identity, project, run.payload["snapshot"], profile)
    row = Solution(
        id=uuid4(),
        organization_id=project.organization_id,
        project_id=project.id,
        conversation_id=conversation.id,
        workflow_run_id=run.id,
        title=data.title,
        profile_version=profile.version,
        version=0,
    )
    session.add(row)
    session.flush()
    append_version(
        session,
        row,
        identity,
        [empty_section(s) for s in run.workflow["outline"]],
        "采用编排模板，待细化大纲",
    )
    audit(session, identity, "solution.create", row.id)
    session.commit()
    return row


def view(session, identity, row):
    _, project = access(session, identity, row.id)
    run = session.scalar(
        select(GenerationRun)
        .where(
            GenerationRun.project_id == project.id,
            GenerationRun.payload["solution_id"].astext == str(row.id),
        )
        .order_by(GenerationRun.created_at.desc())
        .limit(1)
    )
    return dict(
        id=row.id,
        project_id=row.project_id,
        title=row.title,
        status=row.status,
        version=row.version,
        current=current(session, row),
        writable=profile_view(session, identity, project.id)["writable"],
        run=RunView.model_validate(run).model_dump(mode="json") if run else None,
    )


def versions(session, identity, solution_id, after=0):
    row, _ = access(session, identity, solution_id)
    return list(
        session.scalars(
            select(SolutionVersion)
            .where(SolutionVersion.solution_id == row.id, SolutionVersion.version > after)
            .order_by(SolutionVersion.version)
            .limit(50)
        )
    )


def version(session, identity, solution_id, number):
    row, _ = access(session, identity, solution_id)
    result = session.scalar(
        select(SolutionVersion).where(
            SolutionVersion.solution_id == row.id, SolutionVersion.version == number
        )
    )
    if result is None:
        raise missing()
    return result


def start(session, identity, solution_id, data, mode, section_id=None):
    row, project = access(session, identity, solution_id, True)
    original = dict(mode=mode, section_id=section_id, **data.model_dump(mode="json"))
    prior = session.scalar(
        select(GenerationRun).where(
            GenerationRun.conversation_id == row.conversation_id,
            GenerationRun.request_id == data.request_id,
        )
    )
    if prior:
        if prior.payload.get("request") != original or prior.payload.get("solution_id") != str(
            row.id
        ):
            raise AppError(409, "REQUEST_REUSED", "请求编号已用于不同操作。")
        return prior
    check_version(row, data.version)
    active_check(session, project.id)
    profile, ready = ready_profile(session, project)
    if not ready:
        raise AppError(409, "REQUIREMENTS_UNCONFIRMED", "请补齐并确认需求档案。")
    # A reset invalidates old runs, but new explicit generation may use the new epoch.
    from solution_copilot.domain.models import Conversation

    conversation = session.get(Conversation, row.conversation_id)
    sections = copy.deepcopy(current(session, row).sections)
    if mode in {"outline", "approve"} and row.status != "outlining":
        raise AppError(409, "OUTLINE_APPROVED", "大纲已确认；请使用单章重生成。")
    if mode == "section":
        if row.status == "outlining" or not any(s["id"] == section_id for s in sections):
            raise AppError(409, "SECTION_UNAVAILABLE", "请先确认大纲并选择已有章节。")
        remaining = [section_id]
    elif mode == "approve":
        if profile.version != row.profile_version:
            raise AppError(409, "PROFILE_CHANGED", "需求已变化，请重新生成大纲再确认。")
        old = {s["id"]: s for s in sections}
        sections = []
        for s in data.sections:
            value = s.model_dump()
            if s.id in old and old[s.id]["title"] == s.title and old[s.id]["goal"] == s.goal:
                sections.append(old[s.id])
            else:
                sections.append(empty_section(value))
        append_version(session, row, identity, sections, "确认大纲")
        remaining = [s["id"] for s in sections]
        if row.version + len(remaining) > 200:
            raise AppError(422, "VERSION_LIMIT", "剩余版本空间不足以生成全部章节。")
    else:
        remaining = ["outline"]
    row.status = "outlining" if mode == "outline" else "generating"
    run = GenerationRun(
        id=uuid4(),
        organization_id=row.organization_id,
        project_id=project.id,
        conversation_id=row.conversation_id,
        actor_user_id=identity.user_id,
        request_id=data.request_id,
        payload=dict(
            kind="solution",
            solution_id=str(row.id),
            epoch=conversation.epoch,
            profile_version=profile.version,
            base_version=row.version,
            request=original,
            remaining=remaining,
        ),
        events=[],
    )
    session.add(run)
    audit(session, identity, "solution.generate", row.id, mode=mode)
    session.commit()
    return run


def edit(session, identity, solution_id, data):
    row, _ = access(session, identity, solution_id, True)
    prior = session.scalar(
        select(SolutionVersion).where(
            SolutionVersion.solution_id == row.id, SolutionVersion.request_id == data.request_id
        )
    )
    if prior:
        if prior.request_data != data.model_dump(mode="json"):
            raise AppError(409, "REQUEST_REUSED", "请求编号已用于不同编辑。")
        return row
    check_version(row, data.version)
    if row.status == "outlining":
        raise AppError(409, "OUTLINE_REQUIRED", "请先确认大纲。")
    sections = copy.deepcopy(current(session, row).sections)
    section = next((s for s in sections if s["id"] == data.section_id), None)
    if section is None:
        raise missing()
    section["content"], section["status"] = data.content, "draft"
    section["warnings"] = ["人工编辑内容待核实；来源快照保留，不能视为已验证。"]
    for citation in section["citations"]:
        citation["verification_status"] = "unverified"
    append_version(session, row, identity, sections, data.change_summary, request=data)
    row.status = "draft"
    audit(
        session, identity, "solution.edit", row.id, version=row.version, section_id=data.section_id
    )
    session.commit()
    return row
