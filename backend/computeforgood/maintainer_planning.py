"""Private owner planning; agents propose, browser owners approve and dispatch.

Planning mutations lock existing tasks in ID order before their project. Claim
locks its task before the project, matching operator suspension lock order.
Existing acquired contracts are immutable even after the lease is released.
"""
from typing import Literal
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from .config import settings
from .models import Improvement, Lease, PlanningAction, Project, ProjectGoal, Submission, Task
from .schemas import Risk, Tier
from . import services as s

Kind = Literal["FEATURE", "BUG", "DOCS", "TESTS", "PERFORMANCE"]
GoalStatus = Literal["ACTIVE", "PAUSED", "COMPLETED"]
ImprovementStatus = Literal["PROPOSED", "APPROVED", "IN_PROGRESS", "ACCEPTANCE", "DONE", "REJECTED"]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="after")
    def meaningful_fields(self):
        for key, value in self.model_dump().items():
            if value is None:
                if key != "goal_id" and key in self.model_fields_set:
                    raise ValueError(f"{key} cannot be null")
                continue
            if isinstance(value, str) and key not in {"description", "in_scope", "out_of_scope"} and not value.strip():
                raise ValueError(f"{key} cannot be blank")
            if isinstance(value, list) and any(not item.strip() or len(item) > 2000 for item in value):
                raise ValueError(f"{key} entries must contain 1 to 2000 characters")
        return self


class GoalCreate(StrictBody):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20000)
    priority: int = Field(default=3, ge=1, le=5)


class GoalEdit(StrictBody):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    priority: int | None = Field(default=None, ge=1, le=5)
    status: GoalStatus | None = None


class ImprovementCreate(StrictBody):
    goal_id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=300)
    problem: str = Field(min_length=1, max_length=20000)
    outcome: str = Field(min_length=1, max_length=20000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=100)
    in_scope: str = Field(default="", max_length=20000)
    out_of_scope: str = Field(default="", max_length=20000)
    kind: Kind = "FEATURE"
    priority: int = Field(default=3, ge=1, le=5)


class ImprovementEdit(StrictBody):
    version: int = Field(ge=1)
    goal_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    problem: str | None = Field(default=None, min_length=1, max_length=20000)
    outcome: str | None = Field(default=None, min_length=1, max_length=20000)
    acceptance_criteria: list[str] | None = Field(default=None, min_length=1, max_length=100)
    in_scope: str | None = Field(default=None, max_length=20000)
    out_of_scope: str | None = Field(default=None, max_length=20000)
    kind: Kind | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    status: ImprovementStatus | None = None


class DraftTask(StrictBody):
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=20000)
    difficulty: Literal["EASY", "MEDIUM", "HARD", "EXPERT"] = "EASY"
    risk: Risk = "LOW"
    required_model_tier: Tier = "BASIC"
    estimated_minutes: int = Field(default=45, ge=1, le=1440)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=100)
    allowed_paths: list[str] = Field(min_length=1, max_length=100)
    forbidden_paths: list[str] = Field(default_factory=list, max_length=100)
    verification_commands: list[str] = Field(min_length=1, max_length=100)


class TaskEdit(StrictBody):
    version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    difficulty: Literal["EASY", "MEDIUM", "HARD", "EXPERT"] | None = None
    risk: Risk | None = None
    required_model_tier: Tier | None = None
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    acceptance_criteria: list[str] | None = Field(default=None, min_length=1, max_length=100)
    allowed_paths: list[str] | None = Field(default=None, min_length=1, max_length=100)
    forbidden_paths: list[str] | None = Field(default=None, max_length=100)
    verification_commands: list[str] | None = Field(default=None, min_length=1, max_length=100)


class VersionBody(StrictBody):
    version: int = Field(ge=1)


def browser_authority(user):
    if hasattr(user, "credential_scopes") and not demo_browser_authority(user):
        s.fail(403, "Browser owner login required")


def demo_browser_authority(user):
    # Only the explicit local demo identity can simulate a browser. A real PAT
    # issued to a demo account still has the ordinary credential restrictions.
    return settings.demo_mode and user.is_demo and getattr(user, "credential_is_demo", False)


def owned_project(db, project_id, user, lock=False):
    if hasattr(user, "credential_scopes") and "project:plan" not in user.credential_scopes and not demo_browser_authority(user):
        s.fail(403, "Project planning scope required")
    query = select(Project).where(or_(Project.id == project_id, Project.slug == project_id))
    candidate = db.scalar(query)
    operator_browser = user.role == "operator" and (not hasattr(user, "credential_scopes") or demo_browser_authority(user))
    if not candidate or candidate.is_demo and not settings.demo_mode or candidate.maintainer_id != user.id and not operator_browser:
        s.fail(404, "Owned project not found")
    if lock:
        db.scalars(select(Task).where(Task.project_id == candidate.id).order_by(Task.id).with_for_update().execution_options(populate_existing=True)).all()
        query = query.with_for_update().execution_options(populate_existing=True)
    row = db.scalar(query)
    if not row or row.is_demo and not settings.demo_mode or row.maintainer_id != user.id and not operator_browser:
        s.fail(404, "Owned project not found")
    return row


def child(db, model, child_id, project_id):
    row = db.scalar(select(model).where(model.id == child_id, model.project_id == project_id))
    if not row:
        s.fail(404, "Planning item not found")
    return row


def dto(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def audit(db, user, project, action, row, details):
    db.add(PlanningAction(project_id=project.id, user_id=user.id, action=action, target_id=row.id, details=details))
    s.event(db, action, row.id, "Project planning updated", user.id)


def check_version(row, version):
    if row.version != version:
        s.fail(409, "Planning item changed; refresh and retry")


def contract_locked(db, task):
    return bool(db.scalar(select(Lease.id).where(Lease.task_id == task.id).limit(1)) or db.scalar(select(Submission.id).where(Submission.task_id == task.id)))


def task_visibility_condition(user):
    """Legacy drafts retain their existing visibility; owner roadmap drafts do not."""
    public = or_(Task.status != "DRAFT", Task.improvement_id.is_(None))
    if not user:
        return public
    browser = not hasattr(user, "credential_scopes") or demo_browser_authority(user)
    if browser and user.role == "operator":
        return True
    if browser or "project:plan" in getattr(user, "credential_scopes", []):
        return or_(public, Task.project_id.in_(select(Project.id).where(Project.maintainer_id == user.id)))
    return public


def can_read_task(db, task, user):
    return db.scalar(select(Task.id).where(Task.id == task.id, task_visibility_condition(user))) is not None


def tasks_for(db, improvement, lock=False):
    query = select(Task).where(Task.improvement_id == improvement.id).order_by(Task.id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalars(query).all()


def hold_tasks(db, rows):
    for task in rows:
        # Active attempts continue; only AVAILABLE work is removed from dispatch.
        if task.status == "AVAILABLE":
            task.status = "DRAFT"
            task.version += 1


def validate_contract(task):
    if not task.title.strip() or not task.description.strip() or not task.acceptance_criteria or not task.verification_commands or not task.allowed_paths:
        s.fail(422, "Provide a task description, acceptance criteria, allowed paths, and verification commands")
    if not all(v.strip() and len(v) <= 2000 for v in task.acceptance_criteria + task.verification_commands + task.allowed_paths + task.forbidden_paths):
        s.fail(422, "Task contract entries must contain 1 to 2000 characters")
    if s.TIERS[task.required_model_tier] < s.TIERS[s.MIN_TIER[task.risk]]:
        s.fail(422, "Model tier is below the hard minimum for this risk")


def check_dispatch(db, task):
    """Only new leases use this guard; frozen active work remains resumable."""
    if not task.improvement_id:
        return
    improvement = db.get(Improvement, task.improvement_id)
    if not improvement or improvement.project_id != task.project_id or improvement.status not in {"APPROVED", "IN_PROGRESS"}:
        s.fail(403, "Improvement is not approved for dispatch")
    if improvement.goal_id:
        goal = db.get(ProjectGoal, improvement.goal_id)
        if not goal or goal.project_id != task.project_id or goal.status != "ACTIVE":
            s.fail(403, "Project goal is paused or completed")


def project_plan(db, project_id, user):
    project = owned_project(db, project_id, user)
    return {"project": s.project_dto(project),
            "goals": [dto(row) for row in db.scalars(select(ProjectGoal).where(ProjectGoal.project_id == project.id).order_by(ProjectGoal.priority, ProjectGoal.created_at))],
            "improvements": [dto(row) for row in db.scalars(select(Improvement).where(Improvement.project_id == project.id).order_by(Improvement.priority, Improvement.created_at))],
            "tasks": [s.task_dto(db, row, user) for row in db.scalars(select(Task).where(Task.project_id == project.id).order_by(Task.created_at))],
            "submissions": [s.submission_dto(db, row, user) for row in db.scalars(select(Submission).join(Task).where(Task.project_id == project.id).order_by(Submission.created_at.desc()))]}


def propose_improvement(db, project_id, body, user):
    project = owned_project(db, project_id, user, True)
    if body.goal_id:
        child(db, ProjectGoal, body.goal_id, project.id)
    row = Improvement(project_id=project.id, **body.model_dump(), status="PROPOSED")
    db.add(row)
    db.flush()
    audit(db, user, project, "improvement.proposed", row, {"version": row.version})
    return dto(row)


def draft_task(db, project_id, improvement_id, body, user):
    project = owned_project(db, project_id, user, True)
    improvement = child(db, Improvement, improvement_id, project.id)
    if improvement.status in {"DONE", "REJECTED", "ACCEPTANCE"}:
        s.fail(409, "Improvement is not accepting new task drafts")
    row = Task(project_id=project.id, improvement_id=improvement.id, is_demo=project.is_demo, status="DRAFT", **body.model_dump())
    validate_contract(row)
    db.add(row)
    db.flush()
    audit(db, user, project, "work.drafted", row, {"version": row.version})
    return s.task_dto(db, row, user)


def create_planning_router(database, required_user):
    router = APIRouter(prefix="/api/maintainer/projects")
    db_dep, user_dep = Depends(database, scope="function"), Depends(required_user)

    @router.get("")
    def projects(db=db_dep, user=user_dep):
        if hasattr(user, "credential_scopes") and "project:plan" not in user.credential_scopes and not demo_browser_authority(user):
            s.fail(403, "Project planning scope required")
        query = select(Project).order_by(Project.name)
        if user.role != "operator" or hasattr(user, "credential_scopes") and not demo_browser_authority(user):
            query = query.where(Project.maintainer_id == user.id)
        if not settings.demo_mode:
            query = query.where(Project.is_demo.is_(False))
        return [s.project_dto(row) for row in db.scalars(query)]

    @router.get("/{project_id}/plan")
    def plan(project_id: str, db=db_dep, user=user_dep):
        return project_plan(db, project_id, user)

    @router.post("/{project_id}/goals", status_code=201)
    def create_goal(project_id: str, body: GoalCreate, db=db_dep, user=user_dep):
        browser_authority(user)
        project = owned_project(db, project_id, user, True)
        row = ProjectGoal(project_id=project.id, **body.model_dump())
        db.add(row)
        db.flush()
        audit(db, user, project, "goal.created", row, {"version": row.version})
        return dto(row)

    @router.patch("/{project_id}/goals/{goal_id}")
    def edit_goal(project_id: str, goal_id: str, body: GoalEdit, db=db_dep, user=user_dep):
        browser_authority(user)
        project = owned_project(db, project_id, user, True)
        row = child(db, ProjectGoal, goal_id, project.id)
        check_version(row, body.version)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        if row.status == "COMPLETED":
            s.fail(409, "Completed goals cannot be changed")
        # Lock every affected task before checking historical acquisition.
        improvements = db.scalars(select(Improvement).where(Improvement.goal_id == row.id)).all()
        rows = [task for improvement in improvements for task in tasks_for(db, improvement, True)]
        if {"title", "description"}.intersection(values) and any(contract_locked(db, task) for task in rows):
            s.fail(409, "Goal contract is frozen after work acquisition")
        for key, value in values.items():
            setattr(row, key, value)
        row.version += 1
        if row.status != "ACTIVE":
            hold_tasks(db, rows)
        audit(db, user, project, "goal.updated", row, {"fields": sorted(values), "version": row.version})
        return dto(row)

    @router.post("/{project_id}/improvements", status_code=201)
    def propose(project_id: str, body: ImprovementCreate, db=db_dep, user=user_dep):
        return propose_improvement(db, project_id, body, user)

    @router.patch("/{project_id}/improvements/{improvement_id}")
    def edit_improvement(project_id: str, improvement_id: str, body: ImprovementEdit, db=db_dep, user=user_dep):
        browser_authority(user)
        project = owned_project(db, project_id, user, True)
        row = child(db, Improvement, improvement_id, project.id)
        check_version(row, body.version)
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        rows = tasks_for(db, row, True)
        contract_fields = {"goal_id", "title", "problem", "outcome", "acceptance_criteria", "in_scope", "out_of_scope", "kind"}
        if contract_fields.intersection(values) and any(contract_locked(db, task) for task in rows):
            s.fail(409, "Improvement contract is frozen after work acquisition")
        if values.get("goal_id"):
            child(db, ProjectGoal, values["goal_id"], project.id)
        transitions = {"PROPOSED": {"APPROVED", "REJECTED"}, "APPROVED": {"PROPOSED", "REJECTED"}, "IN_PROGRESS": {"ACCEPTANCE", "REJECTED"}, "ACCEPTANCE": {"IN_PROGRESS", "DONE", "REJECTED"}, "DONE": set(), "REJECTED": set()}
        new_status = values.get("status", row.status)
        if row.status in {"DONE", "REJECTED"} or new_status != row.status and new_status not in transitions[row.status]:
            s.fail(409, "Invalid improvement status transition")
        if new_status == "DONE" and (not rows or not any(task.status == "MERGED" for task in rows) or any(task.status not in {"MERGED", "CLOSED", "INVALID"} for task in rows)):
            s.fail(409, "Accept results only after all tasks finish and at least one is merged")
        for key, value in values.items():
            setattr(row, key, value)
        row.version += 1
        if row.status not in {"APPROVED", "IN_PROGRESS"}:
            hold_tasks(db, rows)
        audit(db, user, project, "improvement.updated", row, {"fields": sorted(values), "version": row.version})
        return dto(row)

    @router.post("/{project_id}/improvements/{improvement_id}/tasks", status_code=201)
    def create_task(project_id: str, improvement_id: str, body: DraftTask, db=db_dep, user=user_dep):
        return draft_task(db, project_id, improvement_id, body, user)

    @router.patch("/{project_id}/tasks/{task_id}")
    def edit_task(project_id: str, task_id: str, body: TaskEdit, db=db_dep, user=user_dep):
        browser_authority(user)
        project = owned_project(db, project_id, user, True)
        row = child(db, Task, task_id, project.id)
        row = s.get_task(db, row.id, True)
        check_version(row, body.version)
        if not row.improvement_id or row.status not in {"DRAFT", "AVAILABLE"} or contract_locked(db, row):
            s.fail(409, "Acquired task contracts cannot be changed")
        values = body.model_dump(exclude_unset=True, exclude={"version"})
        for key, value in values.items():
            setattr(row, key, value)
        validate_contract(row)
        # Every contract edit requires explicit republication by the browser owner.
        row.status = "DRAFT"
        row.version += 1
        audit(db, user, project, "work.draft_updated", row, {"fields": sorted(values), "version": row.version})
        return s.task_dto(db, row, user)

    @router.post("/{project_id}/tasks/{task_id}/publish")
    def publish(project_id: str, task_id: str, body: VersionBody, db=db_dep, user=user_dep):
        browser_authority(user)
        project = owned_project(db, project_id, user, True)
        row = child(db, Task, task_id, project.id)
        row = s.get_task(db, row.id, True)
        check_version(row, body.version)
        if row.status != "DRAFT" or not row.improvement_id:
            s.fail(409, "Only improvement task drafts can be published")
        if project.status != "VERIFIED":
            s.fail(403, "Project is not verified for dispatch")
        check_dispatch(db, row)
        validate_contract(row)
        row.status = "AVAILABLE"
        row.version += 1
        improvement = db.get(Improvement, row.improvement_id)
        if improvement.status == "APPROVED":
            improvement.status = "IN_PROGRESS"
            improvement.version += 1
        audit(db, user, project, "work.published", row, {"version": row.version})
        return s.task_dto(db, row, user)

    return router
