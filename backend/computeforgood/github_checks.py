"""Fail-closed CI reconciliation from GitHub's current state, never webhook order."""
from urllib.parse import urlparse
import re
import uuid
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select
from .config import settings
from .models import Project, Submission, Task, WebhookDelivery
from . import services as s


def api_json(path):
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10"}
    if settings.github_token:
        headers["Authorization"] = "Bearer " + settings.github_token
    response = httpx.get("https://api.github.com" + path, headers=headers, timeout=12, follow_redirects=False)
    response.raise_for_status()
    return response.json()


def repo_path(project):
    parsed = urlparse(project.repository_url)
    path = parsed.path.rstrip("/").removesuffix(".git")
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise ValueError("Project has an invalid GitHub repository URL")
    return path


def current_pr(submission, project):
    path = urlparse(submission.pr_url).path
    if not re.fullmatch(re.escape(repo_path(project)) + r"/pull/[1-9][0-9]*", path):
        raise ValueError("Submission is outside its project repository")
    return api_json("/repos" + path.replace("/pull/", "/pulls/"))


def enqueue_reconciliation(db, submission):
    """Persist initial/revised-head CI reads in the same transaction as the head.

    This uses the integration queue, including its bounded retry and operator
    retry policy. A queued old head cannot overwrite a later revision.
    """
    if not submission.is_demo:
        db.add(WebhookDelivery(id="reconcile-" + uuid.uuid4().hex,
                              event_type="reconcile_submission",
                              payload={"submission_id": submission.id, "head_sha": submission.head_sha}))


def process_reconciliation(db, delivery):
    candidate = db.get(Submission, delivery.payload.get("submission_id"))
    if candidate is None:
        return
    task = s.get_task(db, candidate.task_id, True)
    row = db.scalar(select(Submission).where(Submission.id == candidate.id)
                    .with_for_update().execution_options(populate_existing=True))
    if row.head_sha == delivery.payload.get("head_sha") and row.status not in {"MERGED", "CLOSED", "INVALID"}:
        if row.is_demo:
            reconcile(db, row)
        else:
            pr = current_pr(row, db.get(Project, task.project_id))
            s.observe_pr_state(db, row, pr, closed=pr.get("state") == "closed")


def reconcile(db, submission):
    task = db.get(Task, submission.task_id)
    project = db.get(Project, task.project_id)
    if submission.is_demo:
        return
    submission.checks_passed = False
    required = project.required_checks or []
    if not required:
        return  # No policy means unverified, not vacuous success.
    prefix = "/repos" + repo_path(project) + "/commits/" + submission.head_sha
    observed = {}
    for page in range(1, 11):
        data = api_json(prefix + f"/check-runs?filter=latest&per_page=100&page={page}")
        runs = data.get("check_runs", [])
        for run in runs:
            if run.get("head_sha", "").lower() != submission.head_sha.lower():
                continue
            name = run.get("name", "")
            good = run.get("status") == "completed" and run.get("conclusion") == "success"
            # Latest runs from different apps with the same name must all succeed.
            key = "check:" + name
            observed[key] = observed.get(key, True) and good
        if len(runs) < 100:
            break
    else:
        raise ValueError("Too many check runs to establish a complete CI result")
    status_count = 0
    for page in range(1, 11):
        data = api_json(prefix + f"/status?per_page=100&page={page}")
        statuses = data.get("statuses", [])
        status_count += len(statuses)
        for status in statuses:
            key = "status:" + status.get("context", "")
            observed[key] = observed.get(key, True) and status.get("state") == "success"
        if len(statuses) < 100:
            if status_count < data.get("total_count", status_count):
                raise ValueError("Incomplete commit statuses; CI cannot be established")
            break
    else:
        raise ValueError("Too many commit statuses to establish a complete CI result")
    def passed(name):
        if name.startswith(("check:", "status:")):
            return observed.get(name, False)
        matching = [v for k, v in observed.items() if k in {"check:" + name, "status:" + name}]
        return bool(matching) and all(matching)
    submission.checks_passed = all(passed(name) for name in required)
    if submission.status not in {"MERGED", "CLOSED", "INVALID"}:
        q = s.quorum(db, submission)
        submission.status = "CHANGES_NEEDED" if q["blocked"] else "AWAITING_MAINTAINER" if q["passed"] and submission.checks_passed else "REVIEWING"
        task.status = submission.status
    s.event(db, "submission.checks_updated", submission.id, "CI reconciled for the current PR commit")


def process_checks_event(db, delivery):
    payload = delivery.payload
    repo = payload.get("repository", {}).get("html_url", "").rstrip("/").lower()
    sha = (payload.get("check_run", {}).get("head_sha") or payload.get("check_suite", {}).get("head_sha") or payload.get("sha", "")).lower()
    if not re.fullmatch(r"[0-9a-f]{7,64}", sha):
        return
    # A missing synchronize event leaves our stored head behind. GitHub check
    # events can identify the PR independently of that old SHA; validate the
    # association by reading its current API state before applying anything.
    check = payload.get("check_run") or payload.get("check_suite") or {}
    references = []
    for pr in check.get("pull_requests", [])[:100]:
        number = pr.get("number")
        if isinstance(number, int) and not isinstance(number, bool) and number > 0:
            references.append(repo + "/pull/" + str(number))
    candidates = db.scalars(select(Submission).join(Task).join(Project).where(
        or_(Submission.head_sha == sha, Submission.pr_url.in_(references)),
        Project.repository_url == repo, Submission.is_demo.is_(False),
        Submission.status.not_in(["MERGED", "CLOSED", "INVALID"]))).all()
    for candidate in candidates:
        task = s.get_task(db, candidate.task_id, True)
        row = db.scalar(select(Submission).where(Submission.id == candidate.id).with_for_update().execution_options(populate_existing=True))
        if (row.head_sha == sha or row.pr_url in references) and row.status not in {"MERGED", "CLOSED", "INVALID"}:
            pr = current_pr(row, db.get(Project, task.project_id))
            s.observe_pr_state(db, row, pr, closed=pr.get("state") == "closed")


def create_integration_router(database, required_user):
    router = APIRouter(prefix="/api/admin")

    @router.get("/integrations")
    def integrations(db=Depends(database, scope="function"), user=Depends(required_user)):
        s.operator(user)
        rows = db.scalars(select(WebhookDelivery).order_by(WebhookDelivery.created_at.desc()).limit(100)).all()
        return {"github_configured": bool(settings.github_token), "oauth_configured": bool(settings.github_client_id and settings.github_client_secret),
                "deliveries": [{k: getattr(row, k) for k in ("id", "event_type", "status", "attempts", "next_attempt_at", "last_attempt_at", "error", "created_at")} for row in rows]}

    @router.post("/integrations/{delivery_id}/retry")
    def retry(delivery_id: str, db=Depends(database, scope="function"), user=Depends(required_user)):
        s.operator(user)
        row = db.scalar(select(WebhookDelivery).where(WebhookDelivery.id == delivery_id).with_for_update())
        if not row:
            raise HTTPException(404, "Delivery not found")
        if row.status != "FAILED":
            raise HTTPException(409, "Only failed deliveries can be retried")
        row.status, row.attempts, row.error, row.next_attempt_at = "PENDING", 0, None, None
        s.event(db, "integration.retry_requested", row.id, "Operator requested failed integration retry", user.id)
        return {"accepted": True}

    @router.post("/submissions/{submission_id}/refresh-checks")
    def refresh(submission_id: str, db=Depends(database, scope="function"), user=Depends(required_user)):
        s.operator(user)
        candidate = db.get(Submission, submission_id)
        if not candidate:
            raise HTTPException(404, "Submission not found")
        s.get_task(db, candidate.task_id, True)
        row = db.scalar(select(Submission).where(Submission.id == submission_id).with_for_update().execution_options(populate_existing=True))
        try:
            if row.status not in {"MERGED", "CLOSED", "INVALID"}:
                if row.is_demo:
                    reconcile(db, row)
                else:
                    pr = current_pr(row, db.get(Project, db.get(Task, row.task_id).project_id))
                    s.observe_pr_state(db, row, pr, closed=pr.get("state") == "closed")
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, "GitHub checks could not be verified")
        return {"head_sha": row.head_sha, "checks_passed": row.checks_passed, "status": row.status}

    return router
