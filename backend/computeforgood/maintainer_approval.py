"""Browser project owners may accept an exact head without fabricating reviews."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from . import services as s
from .governance import audit
from .models import MaintainerApproval
from .review_workflow import locked_submission


class ApprovalBody(BaseModel):
    head_sha: str = Field(pattern=r"^[0-9a-fA-F]{7,64}$")
    approved: bool
    reason: str = Field(min_length=10, max_length=10000)


def create_approval_router(database, required_user):
    router = APIRouter(prefix="/api")

    @router.post("/submissions/{submission_id}/maintainer-approval")
    def decide(submission_id: str, body: ApprovalBody,
               db=Depends(database, scope="function"), user=Depends(required_user)):
        task, submission = locked_submission(db, submission_id)
        db.refresh(user)
        if user.suspended:
            s.fail(401, "Account suspended")
        # An operator role or PAT does not substitute for project ownership.
        if not s.browser_maintainer(db, task.project_id, user):
            s.fail(403, "Project owner browser login required")
        if body.head_sha.lower() != submission.head_sha.lower():
            s.fail(409, "HEAD_CHANGED: accept the current commit")
        if submission.status in {"MERGED", "CLOSED", "INVALID"}:
            s.fail(409, "Terminal submissions cannot be amended")
        if len(body.reason.strip()) < 10:
            s.fail(422, "Explain the project owner's decision")
        row = db.scalar(select(MaintainerApproval).where(
            MaintainerApproval.submission_id == submission.id,
            MaintainerApproval.head_sha == submission.head_sha,
            MaintainerApproval.maintainer_id == user.id,
        ))
        timestamp = s.now(db)
        if row is None:
            row = MaintainerApproval(submission_id=submission.id, head_sha=submission.head_sha,
                                     maintainer_id=user.id)
            db.add(row)
        row.approved, row.reason, row.updated_at = body.approved, body.reason.strip(), timestamp
        db.flush()
        q = s.quorum(db, submission)
        submission.status = "CHANGES_NEEDED" if q["blocked"] else "AWAITING_MAINTAINER" if q["passed"] and submission.checks_passed else "REVIEWING"
        task.status = submission.status
        audit(db, user, "submission.maintainer_approval", submission.id,
              f"head={submission.head_sha}; approved={body.approved}; reason={row.reason}")
        s.event(db, "submission.maintainer_approval", submission.id,
                "Project owner decision recorded for the current commit", user.id)
        return s.submission_dto(db, submission, user, include_reviews=True)

    return router
