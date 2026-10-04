from contextlib import asynccontextmanager
import asyncio
import hashlib
import hmac
import json
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, TimeoutError as PoolTimeoutError
import socketio
from .config import settings
from .db import SessionLocal
from .models import Event, ImpactCredit, Lease, Project, Review, Submission, Task, User, WebhookDelivery
from .schemas import CheckpointBody, PermitBody, ProjectUpdate, ReviewBody, SubmissionBody, TaskCreate, TokenBody
from . import services as s
from . import auth

redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=list(settings.cors_origins), client_manager=socketio.AsyncRedisManager(settings.redis_url, channel="cfg-socketio"), logger=False, engineio_logger=False)


def database():
    with SessionLocal.begin() as db:
        yield db


def optional_user(request: Request, authorization: str | None = Header(default=None), db=Depends(database, scope="function")):
    if authorization is None:
        return auth.resolve_cookie(request, db)
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        raise HTTPException(401, "Bearer token required")
    user = s.authenticate(db, token)
    required = "project:plan" if request.url.path.startswith("/api/maintainer/") and not user.credential_is_demo else "work:read" if request.method in {"GET", "HEAD", "OPTIONS"} else "work:write"
    if required not in user.credential_scopes:
        raise HTTPException(403, "Credential scope does not permit this operation")
    # Agent tokens coordinate work; browser operator authority is a separate
    # boundary. The local demo retains its original test identities.
    admin_operation = request.url.path.startswith("/api/admin/") or request.url.path == "/api/tasks" and request.method != "GET" or request.method == "PATCH" and request.url.path.startswith("/api/projects/")
    if not user.credential_is_demo and admin_operation:
        raise HTTPException(403, "Browser operator login required")
    return user


def required_user(user=Depends(optional_user)):
    if not user:
        raise HTTPException(401, "Bearer token required")
    return user


def read_socket_user(token):
    with SessionLocal() as db:
        return s.authenticate(db, token).id


@sio.event
async def connect(sid, environ, auth):
    if auth and auth.get("token"):
        try:
            user_id = await asyncio.to_thread(read_socket_user, auth["token"])
        except HTTPException:
            return False
        await sio.save_session(sid, {"user_id": user_id})
        await sio.enter_room(sid, f"user:{user_id}")
    else:
        await sio.save_session(sid, {"user_id": None})


@asynccontextmanager
async def lifespan(application):
    # MCP is mounted with its own transport lifetime, never application state.
    if mcp_app is not None:
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
    else:
        yield


api = FastAPI(title="ComputeForGood alpha", version="0.1.0", lifespan=lifespan)
api.add_middleware(auth.OAuthRequestGuard)
api.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True, allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", "X-GitHub-Delivery", "X-Hub-Signature-256", "X-GitHub-Event"])
api.include_router(auth.router)


@api.exception_handler(IntegrityError)
async def integrity_error(request, error):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": "Concurrent operation or duplicate resource; refresh and retry"})


@api.exception_handler(DBAPIError)
@api.exception_handler(PoolTimeoutError)
async def database_error(request, error):
    from fastapi.responses import JSONResponse
    # Do not return SQL, parameters or driver exception text to the caller.
    # PostgreSQL distinguishes bounded query/lock cancellation and retryable
    # conflicts from integrity and application errors.
    code = getattr(getattr(error, "orig", None), "sqlstate", None)
    if isinstance(error, (PoolTimeoutError, OperationalError)) or code in {"55P03", "57014", "40001", "40P01", "53300"} or getattr(error, "connection_invalidated", False):
        return JSONResponse(status_code=503, content={"detail": "Database temporarily busy; retry later"},
                            headers={"Retry-After": "3", "Cache-Control": "no-store"})
    return JSONResponse(status_code=500, content={"detail": "Database operation failed"})


@api.get("/api/health")
def health():
    database_ok, redis_ok = False, False
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            database_ok = True
    except Exception:
        pass
    try:
        redis_ok = bool(redis.ping())
    except Exception:
        pass
    return {"status": "ok" if database_ok and redis_ok else "degraded", "database": database_ok, "redis": redis_ok, "demo_mode": settings.demo_mode}


@api.get("/api/demo/users")
def demo_users(db=Depends(database, scope="function")):
    if not settings.demo_mode:
        raise HTTPException(404, "Demo mode disabled")
    return [{"id": u.id, "username": u.username, "role": u.role, "token": "cfg-demo-" + u.username} for u in db.scalars(select(User).where(User.is_demo.is_(True), User.username.in_(["alice", "bob", "carol", "admin"])).order_by(User.username))]


@api.get("/api/me")
def me(user=Depends(required_user)):
    return {"id": user.id, "username": user.username, "role": user.role}


@api.get("/api/stats")
def stats(db=Depends(database, scope="function")):
    def count(model, *filters):
        query = select(func.count()).select_from(model).where(*filters)
        if not settings.demo_mode and hasattr(model, "is_demo"):
            query = query.where(model.is_demo.is_(False))
        return db.scalar(query)
    review_query = select(func.count()).select_from(Review).join(Submission)
    if not settings.demo_mode:
        review_query = review_query.where(Submission.is_demo.is_(False))
    available_query = select(func.count()).select_from(Task).join(Project).where(Task.status == "AVAILABLE", Project.status == "VERIFIED")
    if not settings.demo_mode:
        available_query = available_query.where(Task.is_demo.is_(False), Project.is_demo.is_(False))
    return {"projects": count(Project, Project.status == "VERIFIED"), "tasks_available": db.scalar(available_query), "submissions": count(Submission), "reviews": db.scalar(review_query), "merged": count(Submission, Submission.status == "MERGED"), "demo_mode": settings.demo_mode}


@api.get("/api/projects")
def projects(db=Depends(database, scope="function")):
    query = select(Project).order_by(Project.name)
    if not settings.demo_mode:
        query = query.where(Project.is_demo.is_(False))
    return [s.project_dto(p) for p in db.scalars(query)]


@api.get("/api/projects/{project_id}")
def project(project_id: str, db=Depends(database, scope="function")):
    row = db.scalar(select(Project).where(or_(Project.id == project_id, Project.slug == project_id)))
    if not row or row.is_demo and not settings.demo_mode:
        raise HTTPException(404, "Project not found")
    return s.project_dto(row)


@api.get("/api/tasks")
def tasks(project_id: str | None = None, risk: str | None = None, status: str | None = None, search: str | None = None, user=Depends(optional_user), db=Depends(database, scope="function")):
    query = select(Task).order_by(Task.id)
    from .maintainer_planning import task_visibility_condition
    query = query.where(task_visibility_condition(user))
    if not settings.demo_mode:
        query = query.where(Task.is_demo.is_(False))
    if project_id:
        query = query.where(Task.project_id == project_id)
    if risk:
        query = query.where(Task.risk == risk.upper())
    if status:
        query = query.where(s.visible_task_status(user) == status.upper())
    if search:
        query = query.where(or_(Task.title.ilike("%" + search + "%"), Task.description.ilike("%" + search + "%")))
    return [s.task_dto(db, t, user) for t in db.scalars(query.limit(200))]


@api.get("/api/tasks/{task_id}")
def task(task_id: str, user=Depends(optional_user), db=Depends(database, scope="function")):
    row = s.get_task(db, task_id)
    from .maintainer_planning import can_read_task
    if row.is_demo and not settings.demo_mode or not can_read_task(db, row, user):
        raise HTTPException(404, "Task not found")
    return s.task_dto(db, row, user)


@api.get("/api/activity")
def activity(user=Depends(required_user), db=Depends(database, scope="function")):
    leases = db.scalars(select(Lease).where(Lease.user_id == user.id).order_by(Lease.acquired_at.desc()).limit(100)).all()
    submissions = db.scalars(select(Submission).where(Submission.author_id == user.id).order_by(Submission.created_at.desc())).all()
    reviews = db.scalars(select(Review).where(Review.reviewer_id == user.id).order_by(Review.created_at.desc())).all()
    events = db.scalars(select(Event).where(Event.user_id == user.id).order_by(Event.created_at.desc()).limit(50)).all()
    return {"leases": [s.lease_dto(l) for l in leases], "submissions": [s.submission_dto(db, v, user) for v in submissions], "reviews": [s.review_dto(r, db.get(Submission, r.submission_id)) for r in reviews], "events": [s.event_dto(e) for e in events]}


@api.get("/api/submissions")
def submissions(user=Depends(optional_user), db=Depends(database, scope="function")):
    query = select(Submission).order_by(Submission.created_at.desc())
    if not settings.demo_mode:
        query = query.where(Submission.is_demo.is_(False))
    return [s.submission_dto(db, row, user) for row in db.scalars(query.limit(100))]


@api.get("/api/submissions/{submission_id}")
def submission(submission_id: str, user=Depends(optional_user), db=Depends(database, scope="function")):
    row = db.get(Submission, submission_id)
    if not row or row.is_demo and not settings.demo_mode:
        raise HTTPException(404, "Submission not found")
    return s.submission_dto(db, row, user, True)


@api.get("/api/review-work")
def review_work(limit: int = 50, user=Depends(required_user), db=Depends(database, scope="function")):
    from .review_workflow import discover_reviews
    return [entry['submission'] for entry in discover_reviews(db, user, limit, max_limit=50)]


@api.get("/api/events")
def events(db=Depends(database, scope="function")):
    if not settings.demo_mode:
        query = select(Event).outerjoin(User, User.id == Event.user_id).where(or_(Event.user_id.is_(None), User.is_demo.is_(False)), Event.kind != "work.seeded", Event.kind != "submission.demo_merged")
        demo_ids = select(Task.id).where(Task.is_demo.is_(True)).union(select(Project.id).where(Project.is_demo.is_(True)), select(Submission.id).where(Submission.is_demo.is_(True)))
        query = query.where(Event.entity_id.not_in(demo_ids))
    else:
        query = select(Event)
    return [s.event_dto(row) for row in db.scalars(query.order_by(Event.created_at.desc()).limit(100))]


@api.post("/api/tasks/{task_id}/claim")
def claim(task_id: str, user=Depends(required_user), db=Depends(database, scope="function")):
    return s.claim(db, task_id, user)


@api.post("/api/leases/{lease_id}/heartbeat")
def heartbeat(lease_id: str, body: TokenBody, user=Depends(required_user), db=Depends(database, scope="function")):
    return s.heartbeat(db, lease_id, body.token, user)


@api.post("/api/leases/{lease_id}/release")
def release(lease_id: str, body: TokenBody, user=Depends(required_user), db=Depends(database, scope="function")):
    return s.release(db, lease_id, body.token, user)


@api.post("/api/leases/{lease_id}/checkpoint")
def checkpoint(lease_id: str, body: CheckpointBody, user=Depends(required_user), db=Depends(database, scope="function")):
    return s.checkpoint(db, lease_id, body, user)


@api.post("/api/tasks/{task_id}/permit")
def prepare(task_id: str, body: PermitBody, user=Depends(required_user), db=Depends(database, scope="function")):
    return s.prepare(db, task_id, body.lease_token, user)


@api.post("/api/tasks/{task_id}/submissions")
def register(task_id: str, body: SubmissionBody, user=Depends(required_user), db=Depends(database, scope="function")):
    return s.register(db, task_id, body, user)


@api.post("/api/submissions/{submission_id}/reviews")
def review(submission_id: str, body: ReviewBody, user=Depends(required_user), db=Depends(database, scope="function")):
    from .review_workflow import submit_review
    return submit_review(db, submission_id, body, user)


@api.patch("/api/projects/{project_id}")
def moderate(project_id: str, body: ProjectUpdate, user=Depends(required_user), db=Depends(database, scope="function")):
    s.operator(user)
    tasks = db.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.id).with_for_update()).all()
    row = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if not row:
        raise HTTPException(404, "Project not found")
    prior_checks = list(row.required_checks or [])
    row.status = body.status
    if body.required_checks is not None:
        row.required_checks = [name.strip() for name in body.required_checks if name.strip()]
    if row.status == "VERIFIED" and not row.is_demo and not row.required_checks:
        raise HTTPException(422, "At least one required deterministic CI check must be configured")
    if row.status == "VERIFIED" and not row.is_demo and not body.readiness_confirmed:
        raise HTTPException(422, "Confirm license, verifier, CI readiness, and maintainer opt-in before verification")
    from .review_workflow import ensure_review_work, close_review_work
    from .governance import audit, release_locked
    for task in tasks:
        submission = db.scalar(select(Submission).where(Submission.task_id == task.id).with_for_update())
        if row.status == "REJECTED":
            release_locked(db, task, user)
            if submission:
                close_review_work(db, submission)
        elif submission and submission.status not in {"MERGED", "CLOSED", "INVALID"}:
            if prior_checks != row.required_checks and not submission.is_demo:
                submission.checks_passed = False
                q = s.quorum(db, submission)
                submission.status = "CHANGES_NEEDED" if q["blocked"] else "REVIEWING"
                task.status = submission.status
            ensure_review_work(db, submission)
    audit(db, user, "project.moderated", row.id, f"Status={body.status}; readiness confirmation={body.readiness_confirmed}; required CI policy={row.required_checks}")
    s.event(db, "project.moderated", row.id, f"Operator changed project status to {row.status}", user.id)
    return s.project_dto(row)


@api.post("/api/tasks")
def create_task(body: TaskCreate, user=Depends(required_user), db=Depends(database, scope="function")):
    s.operator(user)
    project = db.get(Project, body.project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    if s.TIERS[body.required_model_tier] < s.TIERS[s.MIN_TIER[body.risk]]:
        raise HTTPException(422, "Model tier is below the hard minimum for this risk")
    if not all(v.strip() for v in body.acceptance_criteria + body.verification_commands):
        raise HTTPException(422, "Acceptance and verification entries cannot be blank")
    values = body.model_dump(exclude_none=True)
    row = Task(**values, is_demo=project.is_demo)
    db.add(row)
    db.flush()
    s.event(db, "work.created", row.id, "Operator created a task contract", user.id)
    return s.task_dto(db, row, user)


@api.post("/api/demo/submissions/{submission_id}/merge")
def demo_merge(submission_id: str, user=Depends(required_user), db=Depends(database, scope="function")):
    if not settings.demo_mode:
        raise HTTPException(404, "Demo mode disabled")
    s.operator(user)
    candidate = db.get(Submission, submission_id)
    if not candidate:
        raise HTTPException(404, "Submission not found")
    s.get_task(db, candidate.task_id, True)
    row = db.scalar(select(Submission).where(Submission.id == submission_id).with_for_update().execution_options(populate_existing=True))
    return s.merge(db, row, True)


@api.post("/api/webhooks/github")
async def github_webhook(request: Request):
    raw = await request.body()
    if len(raw) > 4 * 1024 * 1024:
        raise HTTPException(413, "Webhook payload too large")
    secret = settings.webhook_secret or ("local-demo-webhook-secret" if settings.demo_mode else "")
    if not secret:
        raise HTTPException(503, "GitHub webhook secret is not configured")
    signature = request.headers.get("X-Hub-Signature-256", "")
    expected = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(401, "Invalid GitHub webhook signature")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    if not delivery_id or len(delivery_id) > 100:
        raise HTTPException(422, "X-GitHub-Delivery is required")
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
    except ValueError:
        raise HTTPException(422, "Invalid JSON webhook payload")
    def accept():
        with SessionLocal.begin() as db:
            # Advisory transaction lock serializes retries of the same delivery.
            db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:delivery))"), {"delivery": delivery_id})
            if db.get(WebhookDelivery, delivery_id):
                return {"accepted": True, "duplicate": True}
            row = WebhookDelivery(id=delivery_id, event_type=request.headers.get("X-GitHub-Event", "pull_request"), payload=payload)
            db.add(row)
            db.flush()
            # These state transitions are short DB-only work. Network reconciliation
            # belongs in the worker and is not performed in the receiver.
            if settings.demo_mode:
                s.process_delivery(db, row)
            return {"accepted": True, "duplicate": False}
    return await asyncio.to_thread(accept)


# The SDK implements authorization/token/registration/revocation handlers.
from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl
from .oauth_provider import provider
api.router.routes.extend(create_auth_routes(provider=provider, issuer_url=AnyHttpUrl(settings.public_url), client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=auth.SCOPES, default_scopes=auth.DEFAULT_SCOPES), revocation_options=RevocationOptions(enabled=True)))
api.router.routes.extend(create_protected_resource_routes(resource_url=AnyHttpUrl(settings.public_url + "/mcp"), authorization_servers=[AnyHttpUrl(settings.public_url)], scopes_supported=auth.SCOPES, resource_name="ComputeForGood"))
from .review_workflow import create_router as create_review_router
from .project_gateway import create_project_router
from .github_checks import create_integration_router
from .operations import create_operations_router
from .governance import create_governance_router
from .maintainer_planning import create_planning_router
api.include_router(create_review_router(database, required_user))
api.include_router(create_project_router(database, required_user))
api.include_router(create_integration_router(database, required_user))
api.include_router(create_operations_router(database, required_user))
api.include_router(create_governance_router(database, required_user))
api.include_router(create_planning_router(database, required_user))

# MCP adapter is provided independently; no tool is advertised until loaded.
try:
    from .mcp_gateway import TOOLS, create_mcp_app
except ModuleNotFoundError as error:
    if error.name != "computeforgood.mcp_gateway":
        raise
    TOOLS, mcp_app = [], None
else:
    mcp_app = create_mcp_app()
    api.mount("/mcp", mcp_app)


@api.get("/api/mcp-info")
def mcp_info():
    return {"url": settings.public_url + "/mcp", "tools": TOOLS, "demo_mode": settings.demo_mode, "auth_methods": ["oauth2.1", "bearer"], "authorization_server": settings.public_url + "/", "scopes": auth.SCOPES}


app = socketio.ASGIApp(sio, other_asgi_app=api, socketio_path="socket.io")
