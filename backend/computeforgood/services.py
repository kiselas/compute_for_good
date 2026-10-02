"""Transactional domain shared by HTTP, MCP, and background workers.

Callers own commit/rollback. Every mutation locks the task before its lease,
permit, or submission, so expiry and finalization use the same lock order.
"""
from datetime import datetime, timedelta
import hashlib
import re
import secrets
from urllib.parse import urlparse
import httpx
from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import object_session
from .config import settings
from .models import ApiCredential, Checkpoint, Event, FindingResolution, ImpactCredit, Lease, Permit, Project, Review, Submission, Task, User, WebhookDelivery

TIERS = {"BASIC": 0, "STRONG": 1, "FRONTIER": 2}
MIN_TIER = {"LOW": "BASIC", "NORMAL": "STRONG", "HIGH": "FRONTIER", "CRITICAL": "FRONTIER"}
QUORUM = {"LOW": 1, "NORMAL": 2, "HIGH": 3, "CRITICAL": 5}


def hash_token(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


def now(db):
    return db.scalar(select(func.clock_timestamp()))


def fail(status, message):
    raise HTTPException(status, message)


def authenticate(db, token):
    if not token:
        fail(401, "Bearer token required")
    credential = db.scalar(select(ApiCredential).where(ApiCredential.token_hash == hash_token(token), ApiCredential.kind == "access", ApiCredential.revoked_at.is_(None), ApiCredential.expires_at > now(db)))
    user = db.get(User, credential.user_id) if credential else db.scalar(select(User).where(User.token_hash == hash_token(token), User.is_demo.is_(True))) if settings.demo_mode else None
    if not user or user.suspended or (user.is_demo and not settings.demo_mode):
        fail(401, "Invalid or suspended credential")
    user.credential_scopes = credential.scopes if credential else ["work:read", "work:write"]
    return user


def operator(user):
    db = object_session(user)
    if db is not None:
        db.refresh(user)
    if user.suspended:
        fail(401, "Account suspended")
    if user.role != "operator":
        fail(403, "Operator permission required")
    if not user.is_demo and hasattr(user, "credential_scopes"):
        fail(403, "Operator actions require browser login")


def event(db, kind, entity_id, message, user_id=None):
    row = Event(kind=kind, entity_id=entity_id, message=message, user_id=user_id)
    db.add(row)
    db.flush()
    return row


def project_dto(row):
    return {key: getattr(row, key) for key in ("id", "slug", "name", "description", "repository_url", "language", "status", "impact_score", "readiness_score", "is_demo", "required_checks", "maintainer_id")}


def lease_dto(row, token=None):
    result = {key: getattr(row, key) for key in ("id", "task_id", "user_id", "expires_at", "status")}
    if token:
        result["token"] = token
    return result


def task_dto(db, row, user=None):
    result = {key: getattr(row, key) for key in ("id", "project_id", "title", "description", "difficulty", "risk", "required_model_tier", "estimated_minutes", "status", "acceptance_criteria", "allowed_paths", "forbidden_paths", "verification_commands", "is_demo")}
    result["active_lease"] = None
    if row.status in {"CHANGES_NEEDED", "AWAITING_MAINTAINER", "REVIEW_PASSED"}:
        submission = db.scalar(select(Submission).where(Submission.task_id == row.id))
        own_review = submission and user and db.scalar(select(Review.id).where(Review.submission_id == submission.id, Review.reviewer_id == user.id, Review.head_sha == submission.head_sha))
        visible = submission and user and (user.role == "operator" or submission.author_id == user.id or own_review)
        if not visible:
            result["status"] = "REVIEWING"
    if user:
        lease = db.scalar(select(Lease).where(Lease.task_id == row.id, Lease.user_id == user.id, Lease.status == "ACTIVE", Lease.expires_at > func.clock_timestamp()))
        if lease:
            result["active_lease"] = lease_dto(lease)
    return result


def event_dto(row):
    return {key: getattr(row, key) for key in ("id", "kind", "entity_id", "message", "created_at")}


def review_dto(row, submission):
    return {**{key: getattr(row, key) for key in ("id", "submission_id", "reviewer_id", "head_sha", "decision", "summary", "findings", "created_at")}, "is_current": row.head_sha == submission.head_sha}


def quorum(db, submission):
    task = db.get(Task, submission.task_id)
    current = db.scalars(select(Review).where(Review.submission_id == submission.id, Review.head_sha == submission.head_sha)).all()
    eligible = [r for r in current if TIERS.get(r.model_tier, -1) >= TIERS[MIN_TIER[task.risk]] and not db.get(User, r.reviewer_id).suspended]
    approved = sum(r.decision == "APPROVE" for r in eligible)
    all_reviews = db.scalars(select(Review).where(Review.submission_id == submission.id)).all()
    blocked = any(r.decision in {"BLOCK", "REQUEST_CHANGES"} for r in current)
    for r in all_reviews:
        for index, finding in enumerate(r.findings):
            if finding["severity"] in {"HIGH", "CRITICAL"}:
                resolution = db.scalar(select(FindingResolution).where(FindingResolution.review_id == r.id, FindingResolution.finding_index == index))
                if not resolution or (submission.head_sha == r.head_sha and resolution.head_sha != submission.head_sha):
                    blocked = True
    return {"required": QUORUM[task.risk], "approved": approved, "blocked": blocked, "passed": approved >= QUORUM[task.risk] and not blocked, "human_required": task.risk == "CRITICAL"}


def submission_dto(db, row, user=None, include_reviews=False):
    result = {key: getattr(row, key) for key in ("id", "task_id", "author_id", "pr_url", "head_sha", "status", "created_at", "is_demo", "checks_passed")}
    own = user and db.scalar(select(Review.id).where(Review.submission_id == row.id, Review.reviewer_id == user.id, Review.head_sha == row.head_sha))
    visible = user and (user.role == "operator" or user.id == row.author_id or own)
    q = quorum(db, row)
    if not visible:
        q = {**q, "approved": 0, "blocked": False, "passed": False, "blind": True}
        if row.status in {"CHANGES_NEEDED", "AWAITING_MAINTAINER", "REVIEW_PASSED"}:
            result["status"] = "REVIEWING"
    result["quorum"] = q
    if include_reviews:
        # Author/operator may address findings. A prospective reviewer sees none.
        result["reviews"] = [review_dto(r, row) for r in db.scalars(select(Review).where(Review.submission_id == row.id).order_by(Review.created_at)).all()] if visible else []
    return result


def get_task(db, task_id, lock=False):
    query = select(Task).where(Task.id == task_id)
    if lock:
        query = query.with_for_update()
    task = db.scalar(query)
    if not task:
        fail(404, "Task not found")
    return task


def reap_task(db, task, timestamp):
    lease = db.scalar(select(Lease).where(Lease.task_id == task.id, Lease.status == "ACTIVE").with_for_update())
    permit = db.scalar(select(Permit).where(Permit.task_id == task.id, Permit.status == "ACTIVE").with_for_update())
    if lease and lease.expires_at <= timestamp:
        lease.status = "EXPIRED"
        if permit:
            permit.status = "REVOKED"
        if task.status in {"CLAIMED", "IN_PROGRESS", "FINALIZING"}:
            task.status = "AVAILABLE"
        event(db, "lease.expired", task.id, "Lease expired; task is available again", lease.user_id)
    elif permit and permit.expires_at <= timestamp:
        permit.status = "EXPIRED"
        if task.status == "FINALIZING":
            task.status = "IN_PROGRESS" if lease and lease.status == "ACTIVE" else "AVAILABLE"
        event(db, "permit.expired", task.id, "Submission permit expired")
    db.flush()


def check_eligibility(db, task, user):
    # Authentication can precede waiting for a task/user lock. Refresh under the
    # acquired domain locks so a committed suspension cannot leave cached access.
    db.refresh(user)
    if user.suspended or (user.is_demo and not settings.demo_mode):
        fail(401, "Account suspended or unavailable")
    project = db.get(Project, task.project_id)
    if not project or project.status != "VERIFIED":
        fail(403, "Project is not verified for dispatch")
    if (task.is_demo or project.is_demo) and not settings.demo_mode:
        fail(403, "Demo data disabled")
    minimum = max(TIERS[task.required_model_tier], TIERS[MIN_TIER[task.risk]])
    if TIERS.get(user.model_tier, -1) < minimum:
        fail(403, "Model tier does not meet task policy")
    # Self-declaration is insufficient for sensitive public work in this alpha.
    if task.risk in {"HIGH", "CRITICAL"} and not task.is_demo:
        fail(403, "Sensitive real work requires verified model attestation; not enabled")


def claim(db, task_id, user):
    # Serialize user concurrency limit before task; no worker locks user rows.
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    task = get_task(db, task_id, True)
    timestamp = now(db)
    reap_task(db, task, timestamp)
    check_eligibility(db, task, user)
    if task.status != "AVAILABLE":
        fail(409, "WORK_ALREADY_CLAIMED: task is not available")
    count = db.scalar(select(func.count()).select_from(Lease).where(Lease.user_id == user.id, Lease.status == "ACTIVE", Lease.expires_at > timestamp))
    if count >= 1:
        fail(409, "CONCURRENCY_LIMIT: release or finish your active lease")
    raw = secrets.token_urlsafe(32)
    lease = Lease(task_id=task.id, user_id=user.id, token_hash=hash_token(raw), expires_at=timestamp + timedelta(seconds=settings.lease_seconds), acquired_at=timestamp, last_heartbeat_at=timestamp)
    db.add(lease)
    task.status = "CLAIMED"
    db.flush()
    event(db, "work.claimed", task.id, "Work reserved with an expiring lease", user.id)
    return lease_dto(lease, raw)


def active_lease(db, lease_id, token, user):
    candidate = db.get(Lease, lease_id)
    if not candidate:
        fail(404, "Lease not found")
    task = get_task(db, candidate.task_id, True)
    lease = db.scalar(select(Lease).where(Lease.id == lease_id).with_for_update().execution_options(populate_existing=True))
    timestamp = now(db)
    if lease.user_id != user.id or not secrets.compare_digest(lease.token_hash, hash_token(token)):
        fail(403, "Lease belongs to another credential")
    if lease.status != "ACTIVE" or lease.expires_at <= timestamp:
        fail(409, "LEASE_EXPIRED: lease is no longer active")
    check_eligibility(db, task, user)
    return task, lease, timestamp


def heartbeat(db, lease_id, token, user):
    task, lease, timestamp = active_lease(db, lease_id, token, user)
    maximum = lease.acquired_at + timedelta(seconds=settings.max_lease_seconds)
    if maximum <= timestamp:
        fail(409, "Maximum lease duration reached")
    lease.expires_at = min(maximum, timestamp + timedelta(seconds=settings.lease_seconds))
    lease.last_heartbeat_at = timestamp
    if task.status == "CLAIMED":
        task.status = "IN_PROGRESS"
    event(db, "lease.heartbeat", task.id, "Active lease heartbeat received", user.id)
    return lease_dto(lease)


def release(db, lease_id, token, user):
    task, lease, _ = active_lease(db, lease_id, token, user)
    if task.status not in {"CLAIMED", "IN_PROGRESS", "FINALIZING"}:
        fail(409, "Task cannot be released in its current state")
    lease.status = "RELEASED"
    task.status = "AVAILABLE"
    db.execute(update(Permit).where(Permit.lease_id == lease.id, Permit.status == "ACTIVE").values(status="REVOKED"))
    event(db, "lease.released", task.id, "Contributor released unfinished work", user.id)
    return lease_dto(lease)


def checkpoint(db, lease_id, body, user):
    task, lease, _ = active_lease(db, lease_id, body.token, user)
    row = Checkpoint(lease_id=lease.id, summary=body.summary, branch_url=body.branch_url)
    db.add(row)
    if task.status == "CLAIMED":
        task.status = "IN_PROGRESS"
    db.flush()
    event(db, "work.checkpoint", task.id, "Contributor saved progress metadata", user.id)
    return {"id": row.id, "summary": row.summary, "created_at": row.created_at}


def prepare(db, task_id, lease_token, user):
    task = get_task(db, task_id, True)
    timestamp = now(db)
    reap_task(db, task, timestamp)
    lease = db.scalar(select(Lease).where(Lease.task_id == task.id, Lease.status == "ACTIVE"))
    if not lease:
        fail(409, "LEASE_EXPIRED: no active lease")
    active_lease(db, lease.id, lease_token, user)
    if task.status not in {"CLAIMED", "IN_PROGRESS"}:
        fail(409, "Task already finalizing or submitted")
    raw = secrets.token_urlsafe(32)
    row = Permit(task_id=task.id, lease_id=lease.id, user_id=user.id, token_hash=hash_token(raw), expires_at=min(lease.expires_at, timestamp + timedelta(seconds=settings.permit_seconds)), task_version=task.version)
    db.add(row)
    task.status = "FINALIZING"
    db.flush()
    event(db, "submission.prepared", task.id, "Short-lived submission permit issued", user.id)
    return {"id": row.id, "token": raw, "expires_at": row.expires_at}


def validate_pr(project, task, user, body, acquired_at=None):
    parsed = urlparse(body.pr_url)
    repo = urlparse(project.repository_url)
    repo_path = repo.path.rstrip("/").removesuffix(".git")
    if parsed.scheme != "https" or parsed.netloc != "github.com" or not re.fullmatch(re.escape(repo_path) + r"/pull/[1-9][0-9]*", parsed.path) or parsed.query or parsed.fragment:
        fail(422, "PR URL must belong to the task GitHub repository")
    if task.is_demo and settings.demo_mode:
        return True
    if not user.github_id:
        fail(403, "Link your GitHub account before registering a real PR")
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = "Bearer " + settings.github_token
    try:
        response = httpx.get("https://api.github.com/repos" + parsed.path.replace("/pull/", "/pulls/"), headers=headers, timeout=12, follow_redirects=False)
        response.raise_for_status()
        pr = response.json()
    except (httpx.HTTPError, ValueError):
        fail(503, "GitHub PR verification unavailable; permit remains unconsumed")
    marker = task.id if task.id.startswith("CFG-") else "CFG-" + task.id
    trailer = pr.get("body") or ""
    if pr.get("head", {}).get("sha") != body.head_sha or pr.get("state") != "open" or not pr.get("title", "").startswith(f"[{marker}]") or f"ComputeForGood-Task: {marker}" not in trailer or f"ComputeForGood-Contributor: @{user.username}" not in trailer or str(pr.get("user", {}).get("id", "")) != user.github_id:
        fail(422, "PR head, author, state, title, or provenance does not match task")
    if acquired_at is not None:
        try:
            created_at = datetime.fromisoformat(pr["created_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            fail(422, "GitHub PR creation timestamp could not be verified")
        # GitHub exposes second precision; do not reject a PR created later in
        # the same second as a microsecond-resolution database acquisition.
        if created_at < acquired_at.replace(microsecond=0):
            fail(422, "PR predates the implementation lease")
    return False


def register(db, task_id, body, user):
    task = get_task(db, task_id, True)
    timestamp = now(db)
    permit = db.scalar(select(Permit).where(Permit.task_id == task.id, Permit.token_hash == hash_token(body.permit_token)).with_for_update())
    if not permit:
        fail(403, "Invalid submission permit")
    if permit.user_id != user.id:
        fail(403, "Submission permit belongs to another contributor")
    if permit.status != "ACTIVE" or permit.expires_at <= timestamp:
        fail(409, "PERMIT_EXPIRED_OR_CONSUMED")
    lease = db.scalar(select(Lease).where(Lease.id == permit.lease_id).with_for_update())
    if not lease or lease.status != "ACTIVE" or lease.expires_at <= timestamp or task.status != "FINALIZING" or task.version != permit.task_version:
        fail(409, "LEASE_EXPIRED_OR_TASK_REASSIGNED")
    check_eligibility(db, task, user)
    if db.scalar(select(Submission.id).where(Submission.pr_url == body.pr_url)):
        fail(409, "PR already registered")
    is_demo = validate_pr(db.get(Project, task.project_id), task, user, body, acquired_at=lease.acquired_at)
    # Network verification may have outlasted the permit or lease.
    timestamp = now(db)
    if permit.expires_at <= timestamp or lease.expires_at <= timestamp:
        fail(409, "Permit or lease expired during verification")
    row = Submission(task_id=task.id, author_id=user.id, pr_url=body.pr_url, head_sha=body.head_sha.lower(), summary=body.summary, is_demo=is_demo, checks_passed=is_demo)
    db.add(row)
    permit.status = "CONSUMED"
    lease.status = "COMPLETED"
    task.status = "REVIEWING"
    db.flush()
    from .review_workflow import ensure_review_work
    ensure_review_work(db, row)
    event(db, "submission.registered", row.id, "Submission registered; independent reviews are available", user.id)
    return submission_dto(db, row)


def review(db, submission_id, body, user):
    candidate = db.get(Submission, submission_id)
    if not candidate:
        fail(404, "Submission not found")
    task = get_task(db, candidate.task_id, True)
    row = db.scalar(select(Submission).where(Submission.id == submission_id).with_for_update().execution_options(populate_existing=True))
    if row.author_id == user.id:
        fail(403, "SELF_REVIEW_FORBIDDEN")
    if body.head_sha.lower() != row.head_sha.lower():
        fail(409, "HEAD_CHANGED: PR changed after the review began; review the current SHA")
    if row.status in {"MERGED", "CLOSED", "INVALID"}:
        fail(409, "Submission no longer accepts reviews")
    check_eligibility(db, task, user)
    if db.scalar(select(Review.id).where(Review.submission_id == row.id, Review.reviewer_id == user.id, Review.head_sha == row.head_sha)):
        fail(409, "Reviewer already submitted for this head SHA")
    result = Review(submission_id=row.id, reviewer_id=user.id, head_sha=row.head_sha, decision=body.decision, summary=body.summary, findings=[f.model_dump() for f in body.findings], model_tier=user.model_tier)
    db.add(result)
    db.flush()
    q = quorum(db, row)
    row.status = "CHANGES_NEEDED" if q["blocked"] else "AWAITING_MAINTAINER" if q["passed"] and row.checks_passed else "REVIEWING"
    task.status = row.status
    # Public event deliberately omits decision, summary, and finding count.
    event(db, "review.submitted", row.id, "Independent review recorded", user.id)
    return review_dto(result, row)


def merge(db, row, demo=False):
    task = get_task(db, row.task_id, True)
    row = db.scalar(select(Submission).where(Submission.id == row.id).with_for_update().execution_options(populate_existing=True))
    if demo and not row.is_demo:
        fail(403, "Demo merge cannot affect a real submission")
    if demo and (not quorum(db, row)["passed"] or not row.checks_passed):
        fail(409, "Review quorum and checks must pass before demo merge")
    if row.status == "MERGED":
        return submission_dto(db, row, db.get(User, row.author_id))
    row.status = "MERGED"
    row.human_approved = True
    task.status = "MERGED"
    from .review_workflow import close_review_work
    close_review_work(db, row)
    if not db.scalar(select(ImpactCredit.id).where(ImpactCredit.submission_id == row.id)):
        db.add(ImpactCredit(submission_id=row.id, user_id=row.author_id, is_demo=row.is_demo))
    event(db, "submission.demo_merged" if demo else "submission.merged", row.id, "Simulated maintainer merge (demo)" if demo else "GitHub maintainer merge observed", row.author_id)
    return submission_dto(db, row, db.get(User, row.author_id))


def process_delivery(db, delivery):
    if delivery.status == "DONE":
        return
    payload = delivery.payload
    if delivery.event_type in {"check_run", "check_suite", "status"}:
        from .github_checks import process_checks_event
        process_checks_event(db, delivery)
    if delivery.event_type == "pull_request":
        pr = payload.get("pull_request", {})
        candidate = db.scalar(select(Submission).where(Submission.pr_url == pr.get("html_url", "")))
        if candidate:
            task = get_task(db, candidate.task_id, True)
            row = db.scalar(select(Submission).where(Submission.id == candidate.id).with_for_update().execution_options(populate_existing=True))
            # Webhooks may arrive out of order. Read real PR state before replacing a head.
            if not row.is_demo:
                from .github_checks import current_pr
                pr = current_pr(row, db.get(Project, task.project_id))
            sha = pr.get("head", {}).get("sha")
            if payload.get("action") == "synchronize" and sha and sha != row.head_sha:
                if not re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
                    fail(422, "Invalid GitHub head SHA")
                row.head_sha = sha.lower()
                row.status = "REVIEWING"
                row.checks_passed = row.is_demo
                row.human_approved = False
                task.status = "REVIEWING"
                from .review_workflow import head_changed
                head_changed(db, row)
                event(db, "submission.updated", row.id, "PR head changed; prior reviews no longer count")
            if not row.is_demo and row.status not in {"MERGED", "CLOSED", "INVALID"}:
                from .github_checks import reconcile
                reconcile(db, row)
            if (row.is_demo and payload.get("action") == "closed") or (not row.is_demo and pr.get("state") == "closed"):
                if pr.get("merged"):
                    merge(db, row)
                else:
                    row.status = "CLOSED"
                    task.status = "CLOSED"
                    from .review_workflow import close_review_work
                    close_review_work(db, row)
                    event(db, "submission.closed", row.id, "PR closed without merge")
    delivery.status = "DONE"
    delivery.attempts += 1
    delivery.error = None
    delivery.next_attempt_at = None
