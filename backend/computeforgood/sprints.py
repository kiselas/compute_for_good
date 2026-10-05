"""Small owner-curated campaigns backed by published task contracts."""
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, select

from . import services as s
from .config import settings
from .models import Project, Sprint, SprintTask, Submission, Task, User
from .maintainer_planning import audit, browser_authority, check_dispatch, owned_project, validate_contract
from .public_growth import accepted_reviews
from .reputation import accepted_outcomes


class SprintCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    title: dict[str, str]
    description: dict[str, str]
    starts_at: datetime
    ends_at: datetime
    response_hours: int = Field(default=72, ge=1, le=168)
    task_ids: list[str] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def valid(self):
        for values, maximum in ((self.title, 200), (self.description, 5000)):
            if set(values) != {"en", "ru", "zh-CN"} or any(not v.strip() or len(v) > maximum for v in values.values()):
                raise ValueError("Provide non-empty English, Russian and Chinese copy")
        if not self.starts_at.tzinfo or not self.ends_at.tzinfo or not timedelta(0) < self.ends_at - self.starts_at <= timedelta(days=31):
            raise ValueError("Use timezone-aware dates, with a sprint duration of 1 to 31 days")
        if len(set(self.task_ids)) != len(self.task_ids) or any(not v or len(v) > 64 for v in self.task_ids):
            raise ValueError("Task IDs must be unique and valid")
        return self


class SprintVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


def sprint_tasks(db, row):
    return db.scalars(select(Task).join(SprintTask, SprintTask.task_id == Task.id)
                      .where(SprintTask.sprint_id == row.id).order_by(Task.id)).all()


def dispatchable(db, task):
    if task.status != "AVAILABLE" or task.risk not in {"LOW", "NORMAL"}:
        return False
    try:
        check_dispatch(db, task)
        return True
    except HTTPException:
        return False


def sprint_dto(db, row, project, private=False):
    now = s.now(db)
    members = sprint_tasks(db, row)
    tasks = [t for t in members if t.project_id == project.id and t.is_demo == project.is_demo
             and (private or t.status != "DRAFT")]
    outcomes = accepted_outcomes(project.is_demo, since=row.starts_at, as_of=min(now, row.ends_at))
    outcomes_for_sprint = (select(outcomes).join(Submission, Submission.id == outcomes.c.submission_id)
                           .join(SprintTask, SprintTask.task_id == Submission.task_id)
                           .where(SprintTask.sprint_id == row.id, outcomes.c.project_id == project.id)).cte("sprint_outcomes")
    results = db.execute(select(outcomes_for_sprint.c.submission_id, Task.title, User.username)
                         .join(Submission, Submission.id == outcomes_for_sprint.c.submission_id)
                         .join(Task, Task.id == Submission.task_id).join(User, User.id == outcomes_for_sprint.c.user_id)
                         .order_by(outcomes_for_sprint.c.credited_at.desc(), Submission.id)).mappings().all()
    reviewers = accepted_reviews(outcomes_for_sprint, project.is_demo).subquery()
    review_count = db.scalar(select(func.count()).select_from(reviewers))
    participants = set(db.scalars(select(outcomes_for_sprint.c.user_id))) | set(db.scalars(select(reviewers.c.user_id)))
    state = "draft" if row.status == "DRAFT" else "paused" if row.status == "PAUSED" else "upcoming" if now < row.starts_at else "ended" if now > row.ends_at else "active"
    return {"id": row.id, "slug": row.slug, "title": row.title, "description": row.description,
            "starts_at": row.starts_at, "ends_at": row.ends_at, "response_hours": row.response_hours,
            "status": row.status, "state": state, "version": row.version, "is_demo": project.is_demo,
            "project": {"id": project.id, "slug": project.slug, "name": project.name},
            "owner": db.scalar(select(User.username).where(User.id == project.maintainer_id, User.suspended.is_(False))),
            "goal": len(members), "accepted": len(results), "participants": len(participants), "accepted_reviews": review_count,
            "available": sum(dispatchable(db, t) for t in tasks) if state == "active" else 0,
            "tasks": [{"id": t.id, "title": t.title, "status": s.task_dto(db, t)["status"], "risk": t.risk,
                       "estimated_minutes": t.estimated_minutes, "available": dispatchable(db, t) and state == "active"} for t in tasks],
            "results": [dict(r) for r in results]}


def public_sprint(db, slug):
    row = db.scalar(select(Sprint).join(Project).join(User, User.id == Project.maintainer_id)
                     .where(Sprint.slug == slug, Sprint.status.in_(["PUBLISHED", "PAUSED"]), Project.status == "VERIFIED", User.suspended.is_(False), User.is_demo == Project.is_demo))
    if not row:
        s.fail(404, "Sprint not found")
    project = db.get(Project, row.project_id)
    if project.is_demo and not settings.demo_mode:
        s.fail(404, "Sprint not found")
    return sprint_dto(db, row, project)


def create_sprint_router(database, required_user):
    router = APIRouter(prefix="/api")
    dep = Depends(database, scope="function")
    auth = Depends(required_user)

    @router.get("/sprints")
    def catalog(demo: bool = False, db=dep):
        if demo and not settings.demo_mode:
            s.fail(404, "Demo mode disabled")
        rows = db.execute(select(Sprint, Project).join(Project).join(User, User.id == Project.maintainer_id)
                          .where(Sprint.status.in_(["PUBLISHED", "PAUSED"]), Project.status == "VERIFIED",
                                 Project.is_demo == demo, User.suspended.is_(False), User.is_demo == demo)
                          .order_by(Sprint.starts_at.desc(), Sprint.id).limit(50)).all()
        return [sprint_dto(db, row, project) for row, project in rows]

    @router.get("/sprints/{slug}")
    def detail(slug: str, db=dep):
        return public_sprint(db, slug)

    @router.get("/maintainer/projects/{project_id}/sprints")
    def owned(project_id: str, db=dep, user=auth):
        browser_authority(user)
        project = owned_project(db, project_id, user)
        return [sprint_dto(db, row, project, True) for row in db.scalars(select(Sprint).where(Sprint.project_id == project.id).order_by(Sprint.created_at.desc()).limit(50))]

    @router.post("/maintainer/projects/{project_id}/sprints", status_code=201)
    def create(project_id: str, body: SprintCreate, db=dep, user=auth):
        browser_authority(user)
        project = owned_project(db, project_id, user, True)
        if body.ends_at <= s.now(db):
            s.fail(422, "Sprint must end in the future")
        if db.scalar(select(func.count()).select_from(Sprint).where(Sprint.project_id == project.id, Sprint.status == "DRAFT")) >= 10:
            s.fail(429, "Ten sprint drafts maximum per project")
        tasks = db.scalars(select(Task).where(Task.id.in_(body.task_ids), Task.project_id == project.id, Task.is_demo == project.is_demo)).all()
        if len(tasks) != len(body.task_ids):
            s.fail(422, "All sprint tasks must belong to this project and realm")
        row = Sprint(project_id=project.id, **body.model_dump(exclude={"task_ids"}))
        db.add(row)
        db.flush()
        db.add_all(SprintTask(sprint_id=row.id, task_id=t.id) for t in tasks)
        db.flush()
        audit(db, user, project, "sprint.drafted", row, {"version": row.version})
        return sprint_dto(db, row, project, True)

    @router.post("/maintainer/projects/{project_id}/sprints/{sprint_id}/{operation}")
    def change(project_id: str, sprint_id: str, operation: Literal["publish", "pause"], body: SprintVersion, db=dep, user=auth):
        browser_authority(user)
        project = owned_project(db, project_id, user, True)
        row = db.scalar(select(Sprint).where(Sprint.id == sprint_id, Sprint.project_id == project.id).with_for_update())
        if not row:
            s.fail(404, "Sprint not found")
        if row.version != body.version:
            s.fail(409, "Sprint changed; reload before continuing")
        if operation == "publish":
            if row.status != "DRAFT" or project.status != "VERIFIED" or not project.maintainer_id:
                s.fail(409, "Publish a draft only after project verification")
            owner = db.get(User, project.maintainer_id)
            if owner.suspended or owner.is_demo != project.is_demo:
                s.fail(409, "Sprint owner must be active in the project realm")
            now = s.now(db)
            if row.ends_at <= now:
                s.fail(422, "Sprint must end in the future")
            tasks = sprint_tasks(db, row)
            if not tasks:
                s.fail(422, "Sprint needs published work")
            for task in tasks:
                if task.project_id != project.id or task.is_demo != project.is_demo or not dispatchable(db, task):
                    s.fail(422, "Sprint requires available LOW/NORMAL tasks in this project")
                validate_contract(task)
            row.status, row.published_at = "PUBLISHED", now
        else:
            if row.status != "PUBLISHED":
                s.fail(409, "Only a published sprint can be paused")
            row.status = "PAUSED"
        row.version += 1
        audit(db, user, project, "sprint." + operation, row, {"version": row.version})
        db.flush()
        return sprint_dto(db, row, project, True)

    return router
