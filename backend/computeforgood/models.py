from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


def uid():
    return str(uuid4())


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(100), unique=True)
    role: Mapped[str] = mapped_column(String(30), default="contributor")
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    model_tier: Mapped[str] = mapped_column(String(20), default="FRONTIER")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    suspended: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    github_id: Mapped[str | None] = mapped_column(String(40), nullable=True, unique=True)


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiCredential(Base):
    __tablename__ = "api_credentials"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    scopes: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    client_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    grant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="access")


class OAuthClient(Base):
    __tablename__ = "oauth_clients"
    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    metadata_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OAuthGrant(Base):
    __tablename__ = "oauth_grants"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    client_id: Mapped[str] = mapped_column(ForeignKey("oauth_clients.id"))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    params: Mapped[dict] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class GitHubLoginState(Base):
    __tablename__ = "github_login_states"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cookie_hash: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(200))
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    repository_url: Mapped[str] = mapped_column(String(500), unique=True)
    language: Mapped[str] = mapped_column(String(40), default="Python")
    status: Mapped[str] = mapped_column(String(30), default="CANDIDATE")
    impact_score: Mapped[int] = mapped_column(Integer, default=0)
    readiness_score: Mapped[int] = mapped_column(Integer, default=0)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    maintainer_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    required_checks: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (CheckConstraint("impact_score BETWEEN 0 AND 100"), CheckConstraint("readiness_score BETWEEN 0 AND 100"))


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    improvement_id: Mapped[str | None] = mapped_column(ForeignKey("improvements.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(20), default="EASY")
    risk: Mapped[str] = mapped_column(String(20), default="LOW")
    required_model_tier: Mapped[str] = mapped_column(String(20), default="BASIC")
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=45)
    status: Mapped[str] = mapped_column(String(40), default="AVAILABLE", index=True)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    allowed_paths: Mapped[list] = mapped_column(JSON, default=list)
    forbidden_paths: Mapped[list] = mapped_column(JSON, default=list)
    verification_commands: Mapped[list] = mapped_column(JSON, default=list)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("estimated_minutes > 0"), CheckConstraint("risk IN ('LOW','NORMAL','HIGH','CRITICAL')"), CheckConstraint("required_model_tier IN ('BASIC','STRONG','FRONTIER')"))


class Lease(Base):
    __tablename__ = "leases"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Encrypted/recoverable lease tokens are unnecessary: client retains claim token.
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("uq_active_task_lease", "task_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),)


class Checkpoint(Base):
    __tablename__ = "checkpoints"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"))
    summary: Mapped[str] = mapped_column(Text)
    branch_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Permit(Base):
    __tablename__ = "permits"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"))
    lease_id: Mapped[str] = mapped_column(ForeignKey("leases.id"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    task_version: Mapped[int] = mapped_column(Integer)
    __table_args__ = (Index("uq_active_task_permit", "task_id", unique=True, postgresql_where=text("status = 'ACTIVE'")),)


class Submission(Base):
    __tablename__ = "submissions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), unique=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    pr_url: Mapped[str] = mapped_column(String(1000), unique=True)
    head_sha: Mapped[str] = mapped_column(String(64))
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(40), default="REVIEWING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    checks_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    human_approved: Mapped[bool] = mapped_column(Boolean, default=False)


class Review(Base):
    __tablename__ = "reviews"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    head_sha: Mapped[str] = mapped_column(String(64))
    decision: Mapped[str] = mapped_column(String(30))
    summary: Mapped[str] = mapped_column(Text, default="")
    findings: Mapped[list] = mapped_column(JSON, default=list)
    model_tier: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("submission_id", "reviewer_id", "head_sha", name="uq_independent_review_head"),)


class ReviewWorkItem(Base):
    __tablename__ = "review_work_items"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    head_sha: Mapped[str] = mapped_column(String(64))
    slot_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="AVAILABLE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("submission_id", "head_sha", "slot_index"),)


class ReviewLease(Base):
    __tablename__ = "review_leases"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    work_item_id: Mapped[str] = mapped_column(ForeignKey("review_work_items.id"))
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), index=True)
    head_sha: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (Index("uq_active_review_work_lease", "work_item_id", unique=True, postgresql_where=text("status = 'ACTIVE'")), Index("uq_active_reviewer_head_lease", "submission_id", "head_sha", "reviewer_id", unique=True, postgresql_where=text("status = 'ACTIVE'")))


class FindingResolution(Base):
    __tablename__ = "finding_resolutions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id"))
    finding_index: Mapped[int] = mapped_column(Integer)
    reviewer_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    head_sha: Mapped[str] = mapped_column(String(64))
    resolver_role: Mapped[str] = mapped_column(String(30))
    evidence: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (UniqueConstraint("review_id", "finding_index"),)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    published: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class WebhookDelivery(Base):
    __tablename__ = "webhook_deliveries"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImpactCredit(Base):
    __tablename__ = "impact_credits"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    submission_id: Mapped[str] = mapped_column(ForeignKey("submissions.id"), unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class OperatorAction(Base):
    __tablename__ = "operator_actions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProjectGoal(Base):
    __tablename__ = "project_goals"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    priority: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("priority BETWEEN 1 AND 5"), CheckConstraint("status IN ('ACTIVE','PAUSED','COMPLETED')"))


class Improvement(Base):
    __tablename__ = "improvements"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    goal_id: Mapped[str | None] = mapped_column(ForeignKey("project_goals.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(300))
    problem: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[list] = mapped_column(JSON, default=list)
    in_scope: Mapped[str] = mapped_column(Text, default="")
    out_of_scope: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(30), default="FEATURE")
    priority: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(30), default="PROPOSED")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (CheckConstraint("priority BETWEEN 1 AND 5"), CheckConstraint("kind IN ('FEATURE','BUG','DOCS','TESTS','PERFORMANCE')"), CheckConstraint("status IN ('PROPOSED','APPROVED','IN_PROGRESS','ACCEPTANCE','DONE','REJECTED')"))


class PlanningAction(Base):
    __tablename__ = "planning_actions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100))
    target_id: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
