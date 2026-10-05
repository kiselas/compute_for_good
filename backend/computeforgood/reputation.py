"""Versioned, read-only recognition derived from canonical accepted outcomes.

No points for accounts, claims, drafts or raw PR/review volume. Recompute from
the ledger so stale reviews and withdrawn/hidden records cannot retain credit.
"""
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, true

from . import services as s
from .models import ImpactCredit, Project, Review, Submission, Task, User

VERSION = "accepted-outcomes-v1"
Metric = Literal["contributions", "reviews", "projects"]
Period = Literal["all", "30d"]
ACHIEVEMENTS = (
    ("first_contribution", "accepted_contributions", 1),
    ("five_contributions", "accepted_contributions", 5),
    ("ten_contributions", "accepted_contributions", 10),
    ("cross_project", "projects_helped", 3),
    ("first_review", "accepted_reviews", 1),
    ("five_reviews", "accepted_reviews", 5),
)


def accepted_outcomes(is_demo, since=None, as_of=None):
    """One canonical credit per PR, with consistent visibility and provenance."""
    query = (select(Submission.id.label("submission_id"), Submission.author_id.label("user_id"),
                    Submission.head_sha, Task.project_id, ImpactCredit.created_at.label("credited_at"))
             .join(ImpactCredit, ImpactCredit.submission_id == Submission.id)
             .join(Task, Task.id == Submission.task_id).join(Project, Project.id == Task.project_id)
             .join(User, User.id == Submission.author_id)
             .where(Submission.status == "MERGED", Submission.human_approved.is_(True),
                    Task.status == "MERGED", Project.status == "VERIFIED", User.suspended.is_(False),
                    ImpactCredit.user_id == Submission.author_id,
                    Submission.is_demo == is_demo, ImpactCredit.is_demo == is_demo,
                    Task.is_demo == is_demo, Project.is_demo == is_demo, User.is_demo == is_demo))
    if since is not None:
        query = query.where(ImpactCredit.created_at >= since)
    if as_of is not None:
        query = query.where(ImpactCredit.created_at <= as_of)
    return query.cte("accepted_outcomes")


def metrics_query(is_demo, *, since=None, as_of=None):
    outcomes = accepted_outcomes(is_demo, since, as_of)
    contributions = (select(outcomes.c.user_id, func.count().label("accepted_contributions"),
                            func.count(func.distinct(outcomes.c.project_id)).label("projects_helped"))
                     .group_by(outcomes.c.user_id).cte("contribution_totals"))
    # Review credit follows the final accepted head, once per reviewer/PR.
    # Historical heads, self-reviews and unmerged PRs earn no ranking progress.
    reviews = (select(Review.reviewer_id.label("user_id"),
                      func.count(func.distinct(Review.submission_id)).label("accepted_reviews"))
               .join(outcomes, (outcomes.c.submission_id == Review.submission_id)
                     & (outcomes.c.head_sha == Review.head_sha))
               .where(Review.reviewer_id != outcomes.c.user_id,
                      Review.created_at <= outcomes.c.credited_at)
               .group_by(Review.reviewer_id).cte("review_totals"))
    return (select(User.id.label("user_id"), User.username,
                   func.coalesce(contributions.c.accepted_contributions, 0).label("accepted_contributions"),
                   func.coalesce(reviews.c.accepted_reviews, 0).label("accepted_reviews"),
                   func.coalesce(contributions.c.projects_helped, 0).label("projects_helped"))
            .outerjoin(contributions, contributions.c.user_id == User.id)
            .outerjoin(reviews, reviews.c.user_id == User.id)
            .where(User.is_demo == is_demo, User.suspended.is_(False)))


def profile_reputation(db, user):
    as_of = s.now(db)
    row = db.execute(metrics_query(user.is_demo, as_of=as_of).where(User.id == user.id)).mappings().one_or_none()
    # Suspension can commit between authentication/profile lookup and this
    # statement. A stale ORM identity must not turn that boundary into a 500.
    if row is None:
        s.fail(404, "Contributor profile not found")
    metrics = {key: int(row[key]) for key in ("accepted_contributions", "accepted_reviews", "projects_helped")}
    declined = db.scalar(select(func.count()).select_from(Submission)
                         .join(Task, Task.id == Submission.task_id).join(Project, Project.id == Task.project_id)
                         .where(Submission.author_id == user.id, Submission.status.in_(["CLOSED", "INVALID"]),
                                Project.status == "VERIFIED", Submission.is_demo == user.is_demo,
                                Task.is_demo == user.is_demo, Project.is_demo == user.is_demo))
    decided = metrics["accepted_contributions"] + declined
    return {"scoring_version": VERSION, "as_of": as_of, "is_demo": user.is_demo, "metrics": metrics,
            "acceptance": {"accepted": metrics["accepted_contributions"], "decided": decided,
                           "rate": round(100 * metrics["accepted_contributions"] / decided, 1) if decided else None},
            "achievements": [{"id": key, "metric": metric, "threshold": threshold,
                              "progress": min(metrics[metric], threshold), "earned": metrics[metric] >= threshold}
                             for key, metric, threshold in ACHIEVEMENTS]}


def leaderboard(db, metric: Metric, period: Period, limit, offset, is_demo):
    as_of = s.now(db)
    totals = metrics_query(is_demo, since=as_of - timedelta(days=30) if period == "30d" else None,
                           as_of=as_of).cte("recognition_totals")
    column = {"contributions": totals.c.accepted_contributions,
              "reviews": totals.c.accepted_reviews, "projects": totals.c.projects_helped}[metric]
    ranked = (select(totals, func.dense_rank().over(order_by=column.desc()).label("rank"))
              .where(column > 0).cte("ranked_contributors"))
    # One statement returns the total and the requested page, even beyond its end.
    page = (select(ranked).order_by(ranked.c.rank, func.lower(ranked.c.username), ranked.c.user_id)
            .offset(offset).limit(limit).cte("recognition_page"))
    total = select(func.count().label("total")).select_from(ranked).cte("recognition_count")
    rows = db.execute(select(total.c.total, page).select_from(total.outerjoin(page, true()))
                      .order_by(page.c.rank, func.lower(page.c.username), page.c.user_id)).mappings().all()
    entries = [{"username": row["username"], "rank": int(row["rank"]),
                "metrics": {key: int(row[key]) for key in ("accepted_contributions", "accepted_reviews", "projects_helped")}}
               for row in rows if row["user_id"] is not None]
    return {"scoring_version": VERSION, "as_of": as_of, "is_demo": is_demo,
            "metric": metric, "period": period, "limit": limit, "offset": offset,
            "total": int(rows[0]["total"]), "entries": entries}


def create_reputation_router(database):
    router = APIRouter(prefix="/api")

    @router.get("/leaderboard")
    def standings(metric: Metric = "contributions", period: Period = "all",
                  limit: int = Query(default=25, ge=1, le=100), offset: int = Query(default=0, ge=0, le=10000),
                  demo: bool = False, db=Depends(database, scope="function")):
        from .config import settings
        if demo and not settings.demo_mode:
            s.fail(404, "Demo mode disabled")
        return leaderboard(db, metric, period, limit, offset, demo)

    return router
