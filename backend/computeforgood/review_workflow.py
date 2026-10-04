"""Independent review leases and auditable iteration of a canonical submission.

The caller owns the transaction. All mutations acquire task -> submission locks;
claim additionally locks the reviewer first to enforce account concurrency.
"""
from datetime import timedelta
import secrets

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, tuple_, update

from . import services as s
from .config import settings
from .models import FindingResolution, Project, Review, ReviewLease, ReviewWorkItem, Submission, Task, User
from .schemas import SubmissionBody, TokenBody


class ReviewClaimBody(BaseModel):
    head_sha: str = Field(pattern=r'^[0-9a-fA-F]{7,64}$')


class ResolutionBody(ReviewClaimBody):
    evidence: str = Field(min_length=10, max_length=10000)


class ResubmissionBody(ReviewClaimBody):
    summary: str | None = Field(default=None, max_length=10000)


def discovery_eligibility(db, user):
    """Apply cheap account/task policy before limiting discovery, not per candidate.

    Mutation paths still revalidate through check_eligibility under their locks.
    Keep these predicates aligned with that policy; listing never grants a lease.
    """
    db.refresh(user)
    if user.suspended or (user.is_demo and not settings.demo_mode):
        s.fail(401, 'Account suspended or unavailable')
    tier = s.TIERS.get(user.model_tier, -1)
    conditions = [
        Project.status == 'VERIFIED',
        Task.required_model_tier.in_([name for name, rank in s.TIERS.items() if rank <= tier]),
        Task.risk.in_([risk for risk, minimum in s.MIN_TIER.items() if s.TIERS[minimum] <= tier]),
        or_(Task.risk.not_in(['HIGH', 'CRITICAL']), Task.is_demo.is_(True)),
    ]
    if not settings.demo_mode:
        conditions.extend([Task.is_demo.is_(False), Project.is_demo.is_(False)])
    return conditions


def review_discovery_query(db, user, *, slots=False):
    """Filter unavailable, self and completed review work before a keyset scan."""
    query = (select(ReviewWorkItem, Submission, Task) if slots else select(Submission, Task))
    if slots:
        query = query.join(Submission, ReviewWorkItem.submission_id == Submission.id).where(
            ReviewWorkItem.status == 'AVAILABLE', ReviewWorkItem.head_sha == Submission.head_sha,
        )
    else:
        query = query.where(select(ReviewWorkItem.id).where(
            ReviewWorkItem.submission_id == Submission.id,
            ReviewWorkItem.head_sha == Submission.head_sha,
            ReviewWorkItem.status == 'AVAILABLE',
        ).exists())
    completed = select(Review.id).where(
        Review.submission_id == Submission.id, Review.reviewer_id == user.id,
        Review.head_sha == Submission.head_sha,
    ).exists()
    return query.join(Task, Submission.task_id == Task.id).join(Project, Task.project_id == Project.id).where(
        *discovery_eligibility(db, user), Submission.author_id != user.id,
        Submission.status.not_in(['MERGED', 'CLOSED', 'INVALID']), ~completed,
    )


def discover_reviews(db, user, limit, *, slots=False, max_limit=5):
    """Scan bounded keyset chunks until enough eligible reviews are found.

    Quorum is deliberately checked by the canonical domain function, including
    findings on prior heads. There is no arbitrary first-100-candidates cutoff.
    DTOs (and their visibility checks) are built only for the returned results.
    """
    limit = max(1, min(limit, 50 if slots else max_limit))
    query = review_discovery_query(db, user, slots=slots)
    ordered = ReviewWorkItem if slots else Submission
    # Freeze this request's catalog boundary: concurrent inserts cannot keep
    # extending the scan while all prior candidates are already complete.
    boundary = db.execute(query.order_by(ordered.created_at.desc(), ordered.id.desc()).limit(1)).first()
    if boundary is None:
        return []
    last_item = boundary[0]
    query = query.where(tuple_(ordered.created_at, ordered.id) <= (last_item.created_at, last_item.id))
    cursor = None
    result = []
    while len(result) < limit:
        page = query
        if cursor is not None:
            page = page.where(tuple_(ordered.created_at, ordered.id) > cursor)
        rows = db.execute(page.order_by(ordered.created_at, ordered.id).limit(100)).all()
        if not rows:
            break
        # Several slots share a submission; do not recalculate its quorum.
        passed = {}
        for row in rows:
            item, submission, task = row if slots else (None, *row)
            if submission.id not in passed:
                passed[submission.id] = s.quorum(db, submission)['passed']
            if passed[submission.id]:
                continue
            entry = {'task': s.task_dto(db, task, user),
                     'submission': s.submission_dto(db, submission, user)}
            if item is not None:
                entry.update({key: getattr(item, key) for key in (
                    'id', 'submission_id', 'head_sha', 'slot_index', 'status', 'created_at',
                )})
            result.append(entry)
            if len(result) == limit:
                break
        last = rows[-1][0]
        cursor = (last.created_at, last.id)
    return result


def locked_submission(db, submission_id):
    candidate = db.get(Submission, submission_id)
    if candidate is None:
        s.fail(404, 'Submission not found')
    task = s.get_task(db, candidate.task_id, lock=True)
    submission = db.scalar(select(Submission).where(Submission.id == submission_id)
                           .with_for_update().execution_options(populate_existing=True))
    return task, submission


def ensure_review_work(db, submission):
    """Create the risk-policy slots once; callers must already hold the task lock."""
    task = s.get_task(db, submission.task_id)
    project = db.get(Project, task.project_id)
    existing = db.scalars(select(ReviewWorkItem).where(
        ReviewWorkItem.submission_id == submission.id,
        ReviewWorkItem.head_sha == submission.head_sha,
    )).all()
    if (submission.status not in {'MERGED', 'CLOSED', 'INVALID'}
            and task.status not in {'INVALID', 'SUSPENDED', 'CANCELLED'}
            and project is not None and project.status == 'VERIFIED'):
        # A project pause ends reservations without erasing completed reviews.
        # Re-verification reopens only unfinished slots for the current head.
        db.execute(update(ReviewWorkItem).where(
            ReviewWorkItem.submission_id == submission.id,
            ReviewWorkItem.head_sha == submission.head_sha,
            ReviewWorkItem.status == 'STALE',
        ).values(status='AVAILABLE'))
        # Keep completed history immutable, but replace reviews that no longer
        # qualify after suspension. Replacement slots have fresh indices on this SHA.
        reviewed = db.scalars(select(Review).where(
            Review.submission_id == submission.id, Review.head_sha == submission.head_sha,
        )).all()
        eligible = sum(not db.get(User, review.reviewer_id).suspended
                       and s.TIERS.get(review.model_tier, -1) >= s.TIERS[s.MIN_TIER[task.risk]]
                       for review in reviewed)
        unfinished = sum(item.status in {'AVAILABLE', 'CLAIMED', 'STALE'} for item in existing)
        start = max((item.slot_index for item in existing), default=-1) + 1
        for index in range(start, start + max(0, s.QUORUM[task.risk] - eligible - unfinished)):
            db.add(ReviewWorkItem(submission_id=submission.id, head_sha=submission.head_sha,
                                  slot_index=index, status='AVAILABLE'))
    db.flush()


def head_changed(db, submission):
    """Invalidate leased review work for prior commits without reopening implementation work."""
    db.execute(update(ReviewLease).where(
        ReviewLease.submission_id == submission.id, ReviewLease.head_sha != submission.head_sha,
        ReviewLease.status == 'ACTIVE',
    ).values(status='STALE'))
    db.execute(update(ReviewWorkItem).where(
        ReviewWorkItem.submission_id == submission.id, ReviewWorkItem.head_sha != submission.head_sha,
    ).values(status='STALE'))
    ensure_review_work(db, submission)


def close_review_work(db, submission):
    """End reservations when GitHub closes or merges the canonical PR."""
    db.execute(update(ReviewLease).where(
        ReviewLease.submission_id == submission.id, ReviewLease.status == 'ACTIVE',
    ).values(status='STALE'))
    db.execute(update(ReviewWorkItem).where(
        ReviewWorkItem.submission_id == submission.id,
        ReviewWorkItem.status.in_(['AVAILABLE', 'CLAIMED']),
    ).values(status='STALE'))


def expire_locked(db, submission, timestamp):
    leases = db.scalars(select(ReviewLease).where(
        ReviewLease.submission_id == submission.id, ReviewLease.status == 'ACTIVE',
    ).order_by(ReviewLease.id).with_for_update()).all()
    for lease in leases:
        obsolete = (lease.head_sha != submission.head_sha
                    or submission.status in {'MERGED', 'CLOSED', 'INVALID'})
        if obsolete or lease.expires_at <= timestamp:
            lease.status = 'STALE' if obsolete else 'EXPIRED'
            item = db.get(ReviewWorkItem, lease.work_item_id)
            item.status = 'STALE' if obsolete else 'AVAILABLE'
            s.event(db, 'review.lease_expired', submission.id,
                    'Independent review reservation ended', lease.reviewer_id)
    db.flush()


def sweep_review_leases(db, limit=100):
    timestamp = s.now(db)
    ids = db.scalars(select(ReviewLease.submission_id).where(
        ReviewLease.status == 'ACTIVE', ReviewLease.expires_at <= timestamp,
    ).distinct().limit(limit)).all()
    for submission_id in ids:
        _, submission = locked_submission(db, submission_id)
        expire_locked(db, submission, timestamp)


def lease_dto(lease, token=None):
    data = {key: getattr(lease, key) for key in (
        'id', 'work_item_id', 'submission_id', 'head_sha', 'reviewer_id',
        'expires_at', 'status',
    )}
    if token:
        data['token'] = token
    return data


def claim_review(db, submission_id, head_sha, user):
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    task, submission = locked_submission(db, submission_id)
    timestamp = s.now(db)
    expire_locked(db, submission, timestamp)
    if user.id == submission.author_id:
        s.fail(403, 'SELF_REVIEW_FORBIDDEN')
    if head_sha.lower() != submission.head_sha.lower():
        s.fail(409, 'HEAD_CHANGED: discover the current review work')
    if submission.status in {'MERGED', 'CLOSED', 'INVALID'} or s.quorum(db, submission)['passed']:
        s.fail(409, 'Review work is already complete')
    s.check_eligibility(db, task, user)
    if db.scalar(select(Review.id).where(
        Review.submission_id == submission.id, Review.reviewer_id == user.id,
        Review.head_sha == submission.head_sha,
    )):
        s.fail(409, 'Reviewer already completed this head')
    if db.scalar(select(ReviewLease.id).where(
        ReviewLease.reviewer_id == user.id, ReviewLease.status == 'ACTIVE',
        ReviewLease.expires_at > timestamp,
    )):
        s.fail(409, 'REVIEW_CONCURRENCY_LIMIT: finish or release your active review lease')
    ensure_review_work(db, submission)
    item = db.scalar(select(ReviewWorkItem).where(
        ReviewWorkItem.submission_id == submission.id,
        ReviewWorkItem.head_sha == submission.head_sha, ReviewWorkItem.status == 'AVAILABLE',
    ).order_by(ReviewWorkItem.slot_index).with_for_update(skip_locked=True))
    if item is None:
        s.fail(409, 'REVIEW_ALREADY_CLAIMED: all current review slots are reserved')
    token = secrets.token_urlsafe(32)
    lease = ReviewLease(work_item_id=item.id, submission_id=submission.id,
                        head_sha=submission.head_sha, reviewer_id=user.id,
                        token_hash=s.hash_token(token), status='ACTIVE', acquired_at=timestamp,
                        last_heartbeat_at=timestamp,
                        expires_at=timestamp + timedelta(seconds=settings.lease_seconds))
    item.status = 'CLAIMED'
    db.add(lease)
    db.flush()
    s.event(db, 'review.claimed', submission.id, 'Independent review reserved', user.id)
    return lease_dto(lease, token)


def owned_lease(db, lease_id, token, user):
    candidate = db.get(ReviewLease, lease_id)
    if candidate is None:
        s.fail(404, 'Review lease not found')
    task, submission = locked_submission(db, candidate.submission_id)
    lease = db.scalar(select(ReviewLease).where(ReviewLease.id == lease_id).with_for_update()
                      .execution_options(populate_existing=True))
    timestamp = s.now(db)
    if lease.reviewer_id != user.id or not secrets.compare_digest(lease.token_hash, s.hash_token(token)):
        s.fail(403, 'Review lease belongs to another credential')
    if (lease.status != 'ACTIVE' or lease.expires_at <= timestamp
            or lease.head_sha != submission.head_sha):
        s.fail(409, 'REVIEW_LEASE_EXPIRED_OR_HEAD_CHANGED')
    if submission.status in {'MERGED', 'CLOSED', 'INVALID'}:
        s.fail(409, 'Submission no longer accepts review work')
    s.check_eligibility(db, task, user)
    return task, submission, lease, timestamp


def heartbeat_review(db, lease_id, token, user):
    _, submission, lease, timestamp = owned_lease(db, lease_id, token, user)
    maximum = lease.acquired_at + timedelta(seconds=settings.max_lease_seconds)
    if maximum <= timestamp:
        s.fail(409, 'Maximum review lease lifetime reached')
    lease.expires_at = min(maximum, timestamp + timedelta(seconds=settings.lease_seconds))
    lease.last_heartbeat_at = timestamp
    s.event(db, 'review.heartbeat', submission.id, 'Independent review heartbeat received', user.id)
    return lease_dto(lease)


def release_review(db, lease_id, token, user):
    _, submission, lease, _ = owned_lease(db, lease_id, token, user)
    lease.status = 'RELEASED'
    db.get(ReviewWorkItem, lease.work_item_id).status = 'AVAILABLE'
    s.event(db, 'review.released', submission.id, 'Independent review released', user.id)
    return lease_dto(lease)


def submit_review(db, submission_id, body, user):
    task, submission = locked_submission(db, submission_id)
    lease_id = getattr(body, 'review_lease_id', None)
    token = getattr(body, 'review_lease_token', None)
    if bool(lease_id) != bool(token):
        s.fail(422, 'Both review lease ID and token are required')
    lease = None
    if lease_id:
        candidate = db.get(ReviewLease, lease_id)
        if candidate is None or candidate.submission_id != submission.id:
            s.fail(403, 'Review lease does not belong to this submission')
        _, lease_submission, lease, _ = owned_lease(db, lease_id, token, user)
        if lease_submission.id != submission.id or lease.head_sha != body.head_sha.lower():
            s.fail(409, 'Review lease does not match this submission head')
    elif not (settings.demo_mode and submission.is_demo):
        s.fail(403, 'A valid independent review lease is required')
    result = s.review(db, submission_id, body, user)
    ensure_review_work(db, submission)
    if lease:
        lease.status = 'COMPLETED'
        db.get(ReviewWorkItem, lease.work_item_id).status = 'COMPLETED'
    else:
        # Legacy direct submission is confined to explicit demo fixtures.
        item = db.scalar(select(ReviewWorkItem).where(
            ReviewWorkItem.submission_id == submission.id,
            ReviewWorkItem.head_sha == submission.head_sha, ReviewWorkItem.status == 'AVAILABLE',
        ).order_by(ReviewWorkItem.slot_index).with_for_update())
        if item:
            item.status = 'COMPLETED'
    return result


def is_finding_resolved(db, review_id, finding_index):
    return bool(db.scalar(select(FindingResolution.id).where(
        FindingResolution.review_id == review_id, FindingResolution.finding_index == finding_index,
    )))


def resolve_finding(db, review_id, finding_index, head_sha, evidence, user):
    review = db.get(Review, review_id)
    if review is None:
        s.fail(404, 'Review not found')
    task, submission = locked_submission(db, review.submission_id)
    db.refresh(user)
    if user.suspended:
        s.fail(401, 'Participant access is suspended')
    if user.id == submission.author_id:
        s.fail(403, 'Authors cannot adjudicate their own findings')
    operator_authority = (user.role == 'operator'
                          and (user.is_demo or not hasattr(user, 'credential_scopes')))
    if user.id != review.reviewer_id and not operator_authority:
        s.fail(403, 'Only the original reviewer or an operator may resolve a finding')
    if head_sha.lower() != submission.head_sha.lower():
        s.fail(409, 'HEAD_CHANGED: resolution evidence must cover the current head')
    if finding_index < 0 or finding_index >= len(review.findings):
        s.fail(404, 'Finding not found')
    if submission.status in {'MERGED', 'CLOSED', 'INVALID'}:
        s.fail(409, 'Terminal submissions cannot be amended')
    if len(evidence.strip()) < 10:
        s.fail(422, 'Provide verification evidence for the finding resolution')
    existing = db.scalar(select(FindingResolution).where(
        FindingResolution.review_id == review.id, FindingResolution.finding_index == finding_index,
    ))
    if existing:
        resolution = existing
    else:
        resolution = FindingResolution(review_id=review.id, finding_index=finding_index,
                                       reviewer_id=user.id, evidence=evidence,
                                       head_sha=submission.head_sha,
                                       resolver_role='ORIGINAL_REVIEWER' if user.id == review.reviewer_id else 'OPERATOR')
        db.add(resolution)
        db.flush()
        s.event(db, 'review.metadata_updated', submission.id,
                'Independent review metadata updated', user.id)
    q = s.quorum(db, submission)
    submission.status = ('CHANGES_NEEDED' if q['blocked'] else 'AWAITING_MAINTAINER'
                         if q['passed'] and submission.checks_passed else 'REVIEWING')
    task.status = submission.status
    return {key: getattr(resolution, key) for key in (
        'id', 'review_id', 'finding_index', 'reviewer_id', 'head_sha', 'resolver_role', 'evidence', 'created_at',
    )}


def resubmit(db, submission_id, head_sha, summary, user):
    task, submission = locked_submission(db, submission_id)
    if submission.author_id != user.id:
        s.fail(403, 'Only the canonical submission author may register its revision')
    if submission.status in {'MERGED', 'CLOSED', 'INVALID'}:
        s.fail(409, 'Terminal submissions cannot be resubmitted')
    if head_sha.lower() == submission.head_sha.lower():
        s.fail(409, 'A new verified PR head is required for resubmission')
    s.check_eligibility(db, task, user)
    is_demo = s.validate_pr(db.get(Project, task.project_id), task, user, SubmissionBody(
        permit_token='existing-canonical-submission', pr_url=submission.pr_url,
        head_sha=head_sha, summary=summary or '',
    ))
    submission.head_sha = head_sha.lower()
    submission.checks_passed = is_demo
    submission.human_approved = False
    if summary is not None:
        submission.summary = summary
    submission.status = 'REVIEWING'
    task.status = 'REVIEWING'
    head_changed(db, submission)
    from .github_checks import enqueue_reconciliation
    enqueue_reconciliation(db, submission)
    s.event(db, 'submission.updated', submission.id,
            'Canonical PR revised; current-head independent reviews are required', user.id)
    return s.submission_dto(db, submission, user, include_reviews=True)


def create_router(database_dependency, user_dependency):
    router = APIRouter(prefix='/api')
    db_dep = Depends(database_dependency, scope='function')
    user_dep = Depends(user_dependency)

    @router.get('/review-tasks')
    def review_tasks(limit: int = 10, db=db_dep, user=user_dep):
        return discover_reviews(db, user, limit, slots=True)

    @router.post('/submissions/{submission_id}/review-claim')
    def claim_endpoint(submission_id: str, body: ReviewClaimBody, db=db_dep, user=user_dep):
        return claim_review(db, submission_id, body.head_sha, user)

    @router.get('/review-leases')
    def review_leases(db=db_dep, user=user_dep):
        rows = db.scalars(select(ReviewLease).where(ReviewLease.reviewer_id == user.id)
                          .order_by(ReviewLease.acquired_at.desc()).limit(100)).all()
        return [lease_dto(row) for row in rows]

    @router.post('/review-leases/{lease_id}/heartbeat')
    def heartbeat_endpoint(lease_id: str, body: TokenBody, db=db_dep, user=user_dep):
        return heartbeat_review(db, lease_id, body.token, user)

    @router.post('/review-leases/{lease_id}/release')
    def release_endpoint(lease_id: str, body: TokenBody, db=db_dep, user=user_dep):
        return release_review(db, lease_id, body.token, user)

    @router.post('/reviews/{review_id}/findings/{finding_index}/resolve')
    def resolution_endpoint(review_id: str, finding_index: int, body: ResolutionBody,
                            db=db_dep, user=user_dep):
        return resolve_finding(db, review_id, finding_index, body.head_sha, body.evidence, user)

    @router.get('/reviews/{review_id}/finding-resolutions')
    def finding_resolutions(review_id: str, db=db_dep, user=user_dep):
        review = db.get(Review, review_id)
        if review is None:
            s.fail(404, 'Review not found')
        submission = db.get(Submission, review.submission_id)
        own_current = db.scalar(select(Review.id).where(
            Review.submission_id == submission.id, Review.reviewer_id == user.id,
            Review.head_sha == submission.head_sha,
        ))
        if (user.role != 'operator' and user.id not in {submission.author_id, review.reviewer_id}
                and not own_current
                and not s.browser_maintainer(db, s.get_task(db, submission.task_id).project_id, user)):
            s.fail(403, 'Review evidence remains blind until your current-head review is submitted')
        rows = db.scalars(select(FindingResolution).where(FindingResolution.review_id == review.id)
                          .order_by(FindingResolution.created_at)).all()
        return [{key: getattr(row, key) for key in (
            'id', 'review_id', 'finding_index', 'reviewer_id', 'head_sha', 'resolver_role', 'evidence', 'created_at',
        )} for row in rows]

    @router.post('/submissions/{submission_id}/resubmit')
    def resubmission_endpoint(submission_id: str, body: ResubmissionBody, db=db_dep, user=user_dep):
        return resubmit(db, submission_id, body.head_sha, body.summary, user)

    return router
