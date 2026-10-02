"""Audited, single-resource operator interventions for a public beta."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from . import services as s
from .models import BrowserSession, Lease, OperatorAction, Permit, Project, ReviewLease, ReviewWorkItem, Submission, Task, User
from .review_workflow import close_review_work
from .schemas import Risk, Tier


class Intervention(BaseModel):
    reason: str = Field(min_length=10, max_length=5000)


class Suspension(Intervention):
    suspended: bool = True


class TaskEdit(Intervention):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=20000)
    risk: Risk | None = None
    required_model_tier: Tier | None = None
    status: str | None = Field(default=None, pattern=r"^(DRAFT|AVAILABLE)$")
    estimated_minutes: int | None = Field(default=None, ge=1, le=1440)
    acceptance_criteria: list[str] | None = Field(default=None, min_length=1, max_length=100)
    verification_commands: list[str] | None = Field(default=None, min_length=1, max_length=100)
    allowed_paths: list[str] | None = Field(default=None, max_length=100)
    forbidden_paths: list[str] | None = Field(default=None, max_length=100)


def audit(db, user, action, target_id, reason):
    if len(reason.strip()) < 10:
        s.fail(422, "Provide an actionable intervention reason")
    row = OperatorAction(user_id=user.id, action=action, target_id=target_id, reason=reason.strip())
    db.add(row)
    db.flush()
    return row


def release_locked(db, task, user):
    leases = db.scalars(select(Lease).where(Lease.task_id == task.id, Lease.status == "ACTIVE").with_for_update()).all()
    for lease in leases:
        lease.status = "REVOKED"
    for permit in db.scalars(select(Permit).where(Permit.task_id == task.id, Permit.status == "ACTIVE").with_for_update()).all():
        permit.status = "REVOKED"
    if task.status in {"CLAIMED", "IN_PROGRESS", "FINALIZING"}:
        task.status = "AVAILABLE"
    s.event(db, "work.operator_released", task.id, "Operator ended an active work reservation", user.id)


def create_governance_router(database, required_user):
    router = APIRouter(prefix="/api/admin")
    db_dep, user_dep = Depends(database, scope="function"), Depends(required_user)

    @router.get("/users")
    def users(db=db_dep, user=user_dep):
        s.operator(user)
        rows = db.scalars(select(User).order_by(User.created_at.desc()).limit(200)).all()
        return [{key: getattr(row, key) for key in ("id", "username", "role", "suspended", "is_demo", "created_at")} for row in rows]

    @router.get("/leases")
    def leases(db=db_dep, user=user_dep):
        s.operator(user)
        rows = db.scalars(select(Lease).where(Lease.status == "ACTIVE").order_by(Lease.acquired_at.desc()).limit(200)).all()
        return [s.lease_dto(row) for row in rows]

    @router.get("/actions")
    def actions(db=db_dep, user=user_dep):
        s.operator(user)
        rows = db.scalars(select(OperatorAction).order_by(OperatorAction.created_at.desc()).limit(200)).all()
        return [{key: getattr(row, key) for key in ("id", "user_id", "action", "target_id", "reason", "created_at")} for row in rows]

    @router.post("/leases/{lease_id}/force-release")
    def force_release(lease_id: str, body: Intervention, db=db_dep, user=user_dep):
        s.operator(user)
        candidate = db.get(Lease, lease_id)
        if not candidate:
            s.fail(404, "Lease not found")
        task = s.get_task(db, candidate.task_id, True)
        lease = db.scalar(select(Lease).where(Lease.id == lease_id).with_for_update().execution_options(populate_existing=True))
        if lease.status != "ACTIVE":
            s.fail(409, "Reservation is no longer active")
        release_locked(db, task, user)
        audit(db, user, "lease.force_release", lease.id, body.reason)
        return s.lease_dto(lease)

    @router.patch("/tasks/{task_id}")
    def edit(task_id: str, body: TaskEdit, db=db_dep, user=user_dep):
        s.operator(user)
        task = s.get_task(db, task_id, True)
        s.reap_task(db, task, s.now(db))
        if task.status not in {"DRAFT", "AVAILABLE"} or db.scalar(select(Submission.id).where(Submission.task_id == task.id)):
            s.fail(409, "Only unclaimed work without a canonical submission can be edited")
        values = body.model_dump(exclude_none=True, exclude={"reason"})
        if not values:
            s.fail(422, "No task changes supplied")
        for key in ("acceptance_criteria", "verification_commands", "allowed_paths", "forbidden_paths"):
            if key in values and any(not value.strip() or len(value) > 10000 for value in values[key]):
                s.fail(422, "Task contract entries must be nonempty and bounded")
        risk = values.get("risk", task.risk)
        tier = values.get("required_model_tier", task.required_model_tier)
        if s.TIERS[tier] < s.TIERS[s.MIN_TIER[risk]]:
            s.fail(422, "Model tier is below the minimum for this risk")
        for key, value in values.items():
            setattr(task, key, value)
        task.version += 1
        audit(db, user, "task.edited", task.id, body.reason)
        s.event(db, "work.updated", task.id, "Operator updated the unclaimed work contract", user.id)
        return s.task_dto(db, task, user)

    @router.post("/tasks/{task_id}/invalidate")
    def invalidate(task_id: str, body: Intervention, db=db_dep, user=user_dep):
        s.operator(user)
        task = s.get_task(db, task_id, True)
        submission = db.scalar(select(Submission).where(Submission.task_id == task.id).with_for_update())
        if task.status in {"MERGED", "CLOSED", "INVALID"}:
            s.fail(409, "Terminal work cannot be invalidated here")
        release_locked(db, task, user)
        task.status = "INVALID"
        task.version += 1
        if submission:
            submission.status = "INVALID"
            close_review_work(db, submission)
        audit(db, user, "task.invalidated", task.id, body.reason)
        s.event(db, "work.invalidated", task.id, "Operator invalidated unsafe or unsuitable work", user.id)
        return s.task_dto(db, task, user)

    @router.post("/projects/{project_id}/suspend")
    def suspend_project(project_id: str, body: Suspension, db=db_dep, user=user_dep):
        s.operator(user)
        # Lock tasks before the project, matching contributor task-first reads.
        tasks = db.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.id).with_for_update()).all()
        project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        if not project:
            s.fail(404, "Project not found")
        project.status = "SUSPENDED" if body.suspended else "CANDIDATE"
        if body.suspended:
            for task in tasks:
                release_locked(db, task, user)
                submission = db.scalar(select(Submission).where(Submission.task_id == task.id).with_for_update())
                if submission:
                    close_review_work(db, submission)
        audit(db, user, "project.suspended" if body.suspended else "project.reopened", project.id, body.reason)
        s.event(db, "project.updated", project.id, "Operator updated project intake status", user.id)
        return s.project_dto(project)

    @router.post("/users/{user_id}/suspend")
    def suspend_user(user_id: str, body: Suspension, db=db_dep, user=user_dep):
        s.operator(user)
        # Serialize administration before taking a target user lock. Two
        # operators suspending each other must not acquire user rows in reverse.
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext("cfg.operator.user-administration"))))
        target = db.scalar(select(User).where(User.id == user_id).with_for_update())
        if not target:
            s.fail(404, "Participant not found")
        if target.id == user.id:
            s.fail(409, "Operators cannot suspend their own access")
        if body.suspended and target.role == "operator":
            # Serialize operator eligibility before checking the remaining count.
            operator_ids = db.scalars(select(User.id).where(User.role == "operator", User.suspended.is_(False)).order_by(User.id).with_for_update()).all()
            if len(operator_ids) <= 1:
                s.fail(409, "At least one active operator must remain")
        target.suspended = body.suspended
        if body.suspended:
            task_ids = set(db.scalars(select(Lease.task_id).where(Lease.user_id == target.id, Lease.status == "ACTIVE")).all())
            review_leases = db.scalars(select(ReviewLease).where(ReviewLease.reviewer_id == target.id, ReviewLease.status == "ACTIVE")).all()
            submission_ids = [lease.submission_id for lease in review_leases]
            task_ids.update(db.scalars(select(Submission.task_id).where(Submission.id.in_(submission_ids))).all())
            for task_id in sorted(task_ids):
                task = s.get_task(db, task_id, True)
                active = db.scalar(select(Lease).where(Lease.task_id == task_id, Lease.user_id == target.id, Lease.status == "ACTIVE"))
                if active:
                    release_locked(db, task, user)
            for lease in db.scalars(select(ReviewLease).where(ReviewLease.reviewer_id == target.id, ReviewLease.status == "ACTIVE").with_for_update().execution_options(populate_existing=True)).all():
                lease.status = "REVOKED"
                db.get(ReviewWorkItem, lease.work_item_id).status = "AVAILABLE"
            for session in db.scalars(select(BrowserSession).where(BrowserSession.user_id == target.id, BrowserSession.revoked_at.is_(None))).all():
                session.revoked_at = s.now(db)
        audit(db, user, "user.suspended" if body.suspended else "user.reinstated", target.id, body.reason)
        s.event(db, "participant.access_updated", target.id, "Operator updated participant access", user.id)
        return {"id": target.id, "username": target.username, "suspended": target.suspended}

    return router
