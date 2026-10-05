"""Maintainer applications and an authenticated contribution profile."""
import re
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from .models import ImpactCredit, Lease, Project, Review, Submission, User
from . import services as s
from .reputation import accepted_outcomes, profile_reputation


class ProjectApplication(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=20, max_length=20000)
    repo_url: str = Field(max_length=500)
    language: str = Field(default="Python", min_length=1, max_length=40)
    impact: str = Field(min_length=20, max_length=5000)


def canonical_repo(value):
    parsed = urlparse(value.strip())
    match = re.fullmatch(r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or not match or parsed.query or parsed.fragment:
        raise HTTPException(422, "Use a GitHub repository URL: https://github.com/owner/repository")
    owner, repo = match.groups()
    repo = repo.removesuffix(".git")
    if owner in {".", ".."} or repo in {"", ".", ".."}:
        raise HTTPException(422, "Invalid repository")
    return f"https://github.com/{owner.lower()}/{repo.lower()}"


def create_project_router(database, required_user):
    router = APIRouter(prefix="/api")

    @router.post("/projects/applications", status_code=201)
    def apply(body: ProjectApplication, db=Depends(database, scope="function"), user=Depends(required_user)):
        repo = canonical_repo(body.repo_url)
        db.execute(select(User.id).where(User.id == user.id).with_for_update())
        pending = db.scalar(select(func.count()).select_from(Project).where(Project.maintainer_id == user.id, Project.status == "CANDIDATE"))
        if pending >= 5:
            raise HTTPException(429, "Five pending project applications maximum; wait for operator review")
        # Lock the canonical URL before checking uniqueness, including case aliases.
        db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:repo, 0))"), {"repo": repo})
        if db.scalar(select(Project.id).where(func.lower(Project.repository_url) == repo)):
            raise HTTPException(409, "This repository already has a project application")
        prefix = re.sub(r"[^a-z0-9]+", "-", body.name.lower()).strip("-")[:65] or "project"
        from .models import uid
        suffix = uid()[:8]
        row = Project(slug=f"{prefix}-{suffix}", name=body.name.strip(), description=f"{body.description.strip()}\n\nIntended impact: {body.impact.strip()}", repository_url=repo,
                      language=body.language.strip(), status="CANDIDATE", maintainer_id=user.id, is_demo=user.is_demo, required_checks=[])
        db.add(row)
        db.flush()
        s.event(db, "project.applied", row.id, "Project submitted for operator verification", user.id)
        return s.project_dto(row)

    @router.get("/me/profile")
    def profile(db=Depends(database, scope="function"), user=Depends(required_user)):
        def count(model, condition):
            return db.scalar(select(func.count()).select_from(model).where(condition))
        return {"user": {"id": user.id, "username": user.username, "role": user.role},
                "stats": {"tasks_claimed": count(Lease, Lease.user_id == user.id),
                          "submissions": count(Submission, Submission.author_id == user.id),
                          "reviews": count(Review, Review.reviewer_id == user.id),
                          "merged": count(Submission, (Submission.author_id == user.id) & (Submission.status == "MERGED")),
                          "impact_credits": count(ImpactCredit, ImpactCredit.user_id == user.id)},
                "reputation": profile_reputation(db, user),
                "projects": [s.project_dto(p) for p in db.scalars(select(Project).where(Project.maintainer_id == user.id).order_by(Project.name)).all()]}

    @router.get("/people/{username}")
    def public_profile(username: str, db=Depends(database, scope="function")):
        from .config import settings
        user = db.scalar(select(User).where(func.lower(User.username) == username.lower(), User.suspended.is_(False)))
        if not user or (user.is_demo and not settings.demo_mode):
            raise HTTPException(404, "Contributor profile not found")
        reputation = profile_reputation(db, user)
        outcomes = accepted_outcomes(user.is_demo, as_of=reputation["as_of"])
        merged = db.scalars(select(Submission).join(outcomes, outcomes.c.submission_id == Submission.id)
                            .where(Submission.author_id == user.id).order_by(outcomes.c.credited_at.desc(), Submission.id).limit(20)).all()
        count = reputation["metrics"]["accepted_contributions"]
        reviews = reputation["metrics"]["accepted_reviews"]
        credits = count
        return {"username": user.username, "is_demo": user.is_demo, "stats": {"merged": count, "reviews": reviews, "impact_credits": credits},
                "reputation": reputation, "contributions": [s.submission_dto(db, row) for row in merged],
                "projects": [s.project_dto(p) for p in db.scalars(select(Project).where(Project.maintainer_id == user.id, Project.status == "VERIFIED", Project.is_demo == user.is_demo)).all()]}

    return router
