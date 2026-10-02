"""Public readiness and operator diagnostics, without exposing credentials/payloads."""
import time
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import func, select, text
from .config import settings
from .db import SessionLocal
from .models import Event, WebhookDelivery
from . import services as s


def create_operations_router(database, required_user):
    router = APIRouter(prefix="/api")
    redis = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)

    @router.get("/ready")
    def ready():
        database_ok = redis_ok = worker_ok = integration_ok = False
        try:
            with SessionLocal() as db:
                db.execute(text("SELECT 1"))
                database_ok = True
        except Exception:
            pass
        try:
            redis_ok = bool(redis.ping())
            value = redis.get("cfg:worker:heartbeat")
            age = time.time() - float(value) if value else 1e9
            worker_ok = 0 <= age < 30
            value = redis.get("cfg:integration-worker:heartbeat")
            age = time.time() - float(value) if value else 1e9
            integration_ok = 0 <= age < 180
        except Exception:
            pass
        okay = database_ok and redis_ok and worker_ok and integration_ok
        return JSONResponse(status_code=200 if okay else 503, content={"status": "ready" if okay else "not_ready", "database": database_ok, "redis": redis_ok, "worker": worker_ok, "integration_worker": integration_ok})

    @router.get("/admin/operations")
    def diagnostics(db=Depends(database, scope="function"), user=Depends(required_user)):
        s.operator(user)
        counts = dict(db.execute(select(WebhookDelivery.status, func.count()).group_by(WebhookDelivery.status)).all())
        pending = db.scalar(select(func.count()).select_from(Event).where(Event.published.is_(False)))
        oldest = db.scalar(select(func.min(Event.created_at)).where(Event.published.is_(False)))
        return {"demo_mode": settings.demo_mode, "public_url": settings.public_url,
                "secure_cookies": settings.secure_cookies, "webhook_secret_configured": bool(settings.webhook_secret),
                "outbox_pending": pending, "outbox_oldest_at": oldest, "webhook_status_counts": counts}

    return router
