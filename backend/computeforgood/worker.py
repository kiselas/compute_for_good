"""Durable outbox + expiry worker. Redis outage leaves events pending in Postgres."""
import logging
import os
import time
from datetime import timedelta
import socketio
from redis import Redis
from sqlalchemy import func, or_, select
from .config import settings
from .db import SessionLocal
from .models import Event, Lease, Permit, Task, WebhookDelivery
from .services import now, process_delivery, reap_task

log = logging.getLogger("cfg.worker")
health_redis = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)


class ReliableRedisManager(socketio.RedisManager):
    def _publish(self, data):
        result = super()._publish(data)
        if result is None:
            raise ConnectionError("Redis publication failed; retaining outbox entry")
        return result


manager = ReliableRedisManager(settings.redis_url, channel="cfg-socketio", write_only=True, redis_options={"socket_timeout": 2, "socket_connect_timeout": 2})


def sweep():
    with SessionLocal.begin() as db:
        timestamp = now(db)
        ids = set(db.scalars(select(Lease.task_id).where(Lease.status == "ACTIVE", Lease.expires_at <= timestamp)).all())
        ids.update(db.scalars(select(Permit.task_id).where(Permit.status == "ACTIVE", Permit.expires_at <= timestamp)).all())
        for task_id in sorted(ids):
            task = db.scalar(select(Task).where(Task.id == task_id).with_for_update(skip_locked=True))
            if task:
                reap_task(db, task, timestamp)
        from .review_workflow import sweep_review_leases
        sweep_review_leases(db)


def dispatch():
    with SessionLocal.begin() as db:
        rows = db.scalars(select(Event).where(Event.published.is_(False)).order_by(Event.created_at).limit(100).with_for_update(skip_locked=True)).all()
        if not rows:
            return
        # One transport packet per durable batch. Polling clients must not need
        # to decode 100 packets at once; the React client invalidates snapshots
        # once per batch rather than starting a request storm for every event.
        changes = [{"event_id": row.id, "kind": row.kind, "entity_id": row.entity_id} for row in rows]
        manager.emit("state_changed", {"event_id": rows[-1].id, "kind": "state.batch", "entity_id": "*", "changes": changes}, namespace="/")
        for row in rows:
            row.published = True


def integrations():
    # Each delivery commits independently; a poisoned payload cannot roll back or
    # starve the following deliveries. SKIP LOCKED permits more than one worker.
    for _ in range(1):
        with SessionLocal.begin() as db:
            timestamp = now(db)
            row = db.scalar(select(WebhookDelivery).where(WebhookDelivery.status == "PENDING",
                or_(WebhookDelivery.next_attempt_at.is_(None), WebhookDelivery.next_attempt_at <= timestamp))
                .order_by(WebhookDelivery.created_at).limit(1).with_for_update(skip_locked=True))
            if row is None:
                break
            row.last_attempt_at = timestamp
            try:
                with db.begin_nested():
                    process_delivery(db, row)
            except Exception as error:
                row.attempts += 1
                # Do not persist exception text that could include request headers/secrets.
                row.error = type(error).__name__ + ": integration reconciliation failed"
                row.status = "FAILED" if row.attempts >= 8 else "PENDING"
                row.next_attempt_at = timestamp + timedelta(seconds=min(3600, 2 ** row.attempts * 5))
                log.warning("Integration %s attempt %s failed (%s)", row.id, row.attempts, type(error).__name__)


def tick():
    sweep()
    integrations()
    dispatch()


def main():
    logging.basicConfig(level=logging.INFO)
    mode = os.getenv("WORKER_MODE", "all")
    operations = {"all": (sweep, integrations, dispatch), "coordination": (sweep, dispatch), "integrations": (integrations,)}
    if mode not in operations:
        raise ValueError("Unknown WORKER_MODE")
    heartbeat_key = "cfg:integration-worker:heartbeat" if mode == "integrations" else "cfg:worker:heartbeat"
    while True:
        healthy = True
        for operation in operations[mode]:
            try:
                operation()
            except Exception:
                healthy = False
                log.exception("Worker operation %s failed; persisted work will retry", operation.__name__)
        if healthy:
            try:
                health_redis.set(heartbeat_key, str(time.time()), ex=300 if mode == "integrations" else 60)
            except Exception:
                log.warning("Worker heartbeat publication failed")
        time.sleep(float(os.getenv("WORKER_INTERVAL", "1")))


if __name__ == "__main__":
    main()
