"""Bounded retention of authentication records, including refresh replay evidence.

Expired GitHub state verifiers have no audit purpose after one day. Inactive
sessions remain for thirty days and credentials for ninety days. Refresh-token
tombstones remain until their original expiry is ninety days old and every
credential in the family has expired, even if the family was explicitly revoked.
OAuth client registrations are persistent configuration and are never removed.
"""
from datetime import timedelta

from sqlalchemy import and_, delete, exists, or_, select, text
from sqlalchemy.orm import aliased

from .db import SessionLocal
from .models import ApiCredential, BrowserSession, GitHubLoginState, OAuthGrant
from .services import now

BATCH_SIZE = 200
STATE_RETENTION = timedelta(days=1)
SESSION_RETENTION = timedelta(days=30)
CREDENTIAL_RETENTION = timedelta(days=90)


def _delete_locked(db, model, condition, batch_size):
    ids = db.scalars(select(model.id).where(condition).order_by(model.expires_at, model.id)
                     .limit(batch_size).with_for_update(skip_locked=True)).all()
    if ids:
        db.execute(delete(model).where(model.id.in_(ids)), execution_options={"synchronize_session": False})
    return len(ids)


def cleanup_login_states(db, timestamp, batch_size=BATCH_SIZE):
    return _delete_locked(db, GitHubLoginState,
                          GitHubLoginState.expires_at <= timestamp - STATE_RETENTION, batch_size)


def cleanup_browser_sessions(db, timestamp, batch_size=BATCH_SIZE):
    cutoff = timestamp - SESSION_RETENTION
    return _delete_locked(db, BrowserSession, or_(BrowserSession.expires_at <= cutoff,
                          BrowserSession.revoked_at <= cutoff), batch_size)


def cleanup_credentials(db, timestamp, batch_size=BATCH_SIZE):
    cutoff = timestamp - CREDENTIAL_RETENTION
    family = aliased(ApiCredential)
    still_within_family_lifetime = exists(select(family.id).where(
        family.grant_id == ApiCredential.grant_id, family.expires_at > timestamp))
    old = or_(ApiCredential.expires_at <= cutoff, ApiCredential.revoked_at <= cutoff)
    eligible = or_(and_(ApiCredential.kind != "refresh", old),
                   and_(ApiCredential.kind == "refresh", ApiCredential.expires_at <= cutoff,
                        ~still_within_family_lifetime))
    removed = _delete_locked(db, ApiCredential,
                             and_(ApiCredential.grant_id.is_(None), eligible), batch_size)
    if removed == batch_size:
        return removed
    # Issuance, rotation, replay detection and revocation all lock the grant
    # first. Keep that ordering; recheck eligibility after obtaining the lock.
    candidates = exists(select(ApiCredential.id).where(
        ApiCredential.grant_id == OAuthGrant.id, eligible))
    grant_ids = db.scalars(select(OAuthGrant.id).where(candidates).order_by(OAuthGrant.id)
                           .limit(batch_size - removed).with_for_update(skip_locked=True)).all()
    if grant_ids:
        removed += _delete_locked(db, ApiCredential,
                                  and_(ApiCredential.grant_id.in_(grant_ids), eligible), batch_size - removed)
    return removed


def cleanup_grants(db, timestamp, batch_size=BATCH_SIZE):
    # A consumed grant owns the token family despite its short authorization-
    # code TTL. Never remove its revocation/replay state while any row survives.
    has_credentials = exists(select(ApiCredential.id).where(ApiCredential.grant_id == OAuthGrant.id))
    old = or_(and_(OAuthGrant.consumed.is_(False), OAuthGrant.expires_at <= timestamp - STATE_RETENTION),
              and_(OAuthGrant.consumed.is_(True), OAuthGrant.expires_at <= timestamp - CREDENTIAL_RETENTION))
    return _delete_locked(db, OAuthGrant, and_(old, ~has_credentials), batch_size)


def sweep_auth_retention():
    counts = {}
    for cleaner in (cleanup_login_states, cleanup_browser_sessions, cleanup_credentials, cleanup_grants):
        # One small transaction per class. Timeouts cap cost even on a legacy
        # database with a large backlog; later sweeps retry without blocking auth.
        with SessionLocal.begin() as db:
            db.execute(text("SET LOCAL statement_timeout = '5s'"))
            db.execute(text("SET LOCAL lock_timeout = '1s'"))
            counts[cleaner.__name__] = cleaner(db, now(db))
    return counts
