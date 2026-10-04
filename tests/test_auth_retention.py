"""Real PostgreSQL retention and refresh-family safety checks.

Each test uses a private schema, including the concurrency check. Retention
never sees or deletes the QA application's existing authentication records.
"""
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from computeforgood.auth_retention import (
    cleanup_browser_sessions, cleanup_credentials, cleanup_grants, cleanup_login_states,
)
from computeforgood.models import ApiCredential, BrowserSession, GitHubLoginState, OAuthClient, OAuthGrant, User


@pytest.fixture
def auth_db(database):
    schema = "qa_retention_" + uuid.uuid4().hex
    with database.engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        # Preserve column types/defaults/indexes without references to real
        # public users, grants or credentials. Fixtures supply all identities.
        for model in (User, BrowserSession, OAuthClient, OAuthGrant, ApiCredential, GitHubLoginState):
            connection.execute(text(f'CREATE TABLE "{schema}"."{model.__tablename__}" '
                                    f'(LIKE public."{model.__tablename__}" INCLUDING ALL)'))
    engine = database.engine.execution_options(schema_translate_map={None: schema})
    try:
        with Session(engine) as db:
            user = User(username="retention_" + uuid.uuid4().hex, token_hash=uuid.uuid4().hex)
            client = OAuthClient(id=uuid.uuid4().hex, metadata_json={})
            db.add_all([user, client])
            db.commit()
            yield db, engine, user.id, client.id
    finally:
        with database.engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))


def instant():
    return datetime.now(timezone.utc)


def credential(user_id, expires_at, *, grant_id=None, kind="access", revoked_at=None):
    return ApiCredential(user_id=user_id, token_hash=uuid.uuid4().hex,
                         name="Isolated retention check", scopes=["work:read"],
                         expires_at=expires_at, grant_id=grant_id, kind=kind, revoked_at=revoked_at)


def test_expired_state_and_inactive_session_retention(auth_db):
    db, _, user_id, _ = auth_db
    timestamp = instant()
    states = [GitHubLoginState(id=uuid.uuid4().hex, cookie_hash="test-hash", verifier="test-only",
                              expires_at=timestamp + age, consumed=consumed)
              for age, consumed in [(timedelta(days=-2), False), (timedelta(hours=-1), True),
                                    (timedelta(minutes=10), False)]]
    sessions = [BrowserSession(user_id=user_id, token_hash=uuid.uuid4().hex,
                               expires_at=timestamp + age, revoked_at=revoked)
                for age, revoked in [(timedelta(days=-31), None), (timedelta(days=-1), None),
                                     (timedelta(days=7), None), (timedelta(days=7), timestamp - timedelta(days=31)),
                                     (timedelta(days=7), timestamp - timedelta(days=1))]]
    db.add_all(states + sessions)
    db.commit()
    assert cleanup_login_states(db, timestamp) == 1
    assert cleanup_browser_sessions(db, timestamp) == 2
    db.commit()
    assert set(db.scalars(select(GitHubLoginState.id))) == {row.id for row in states[1:]}
    assert set(db.scalars(select(BrowserSession.id))) == {sessions[i].id for i in (1, 2, 4)}


def test_refresh_tombstones_survive_a_live_or_not_yet_expired_family(auth_db):
    db, _, user_id, client_id = auth_db
    timestamp = instant()
    grants = [OAuthGrant(client_id=client_id, user_id=user_id, params={}, consumed=True,
                         revoked=revoked, expires_at=timestamp - timedelta(days=120)) for revoked in (False, True)]
    db.add_all(grants)
    db.flush()
    rows = []
    for grant in grants:
        rows += [credential(user_id, timestamp - timedelta(days=100), grant_id=grant.id, kind="refresh",
                            revoked_at=timestamp - timedelta(days=110)),
                 credential(user_id, timestamp + timedelta(days=1), grant_id=grant.id, kind="refresh",
                            revoked_at=timestamp - timedelta(days=110) if grant.revoked else None)]
    db.add_all(rows)
    db.commit()
    assert cleanup_credentials(db, timestamp) == 0
    assert cleanup_grants(db, timestamp) == 0
    db.commit()
    assert len(db.scalars(select(ApiCredential)).all()) == 4
    assert len(db.scalars(select(OAuthGrant)).all()) == 2


def test_dead_family_is_removed_after_retention_but_pending_and_live_grants_remain(auth_db):
    db, _, user_id, client_id = auth_db
    timestamp = instant()
    dead = OAuthGrant(client_id=client_id, user_id=user_id, params={}, consumed=True,
                      expires_at=timestamp - timedelta(days=120))
    stale_pending = OAuthGrant(client_id=client_id, params={}, expires_at=timestamp - timedelta(days=2))
    pending = OAuthGrant(client_id=client_id, params={}, expires_at=timestamp + timedelta(minutes=10))
    recent_consumed = OAuthGrant(client_id=client_id, user_id=user_id, params={}, consumed=True,
                                expires_at=timestamp - timedelta(days=1))
    db.add_all([dead, stale_pending, pending, recent_consumed])
    db.flush()
    rows = [credential(user_id, timestamp - timedelta(days=100), grant_id=dead.id, kind="refresh"),
            credential(user_id, timestamp - timedelta(days=100)),
            credential(user_id, timestamp + timedelta(days=1)),
            credential(user_id, timestamp - timedelta(days=1), revoked_at=timestamp - timedelta(days=1))]
    db.add_all(rows)
    db.commit()
    assert cleanup_grants(db, timestamp) == 1  # The dead family still has its refresh evidence.
    assert cleanup_credentials(db, timestamp) == 2
    assert cleanup_grants(db, timestamp) == 1
    db.commit()
    assert set(db.scalars(select(OAuthGrant.id))) == {pending.id, recent_consumed.id}
    assert set(db.scalars(select(ApiCredential.id))) == {rows[2].id, rows[3].id}
    assert db.get(OAuthClient, client_id) is not None


def test_each_cleanup_is_bounded_and_skips_locked_records(auth_db):
    db, engine, _, _ = auth_db
    timestamp = instant()
    rows = [GitHubLoginState(id=f"{i:04d}", cookie_hash="test-only", verifier="test-only",
                              expires_at=timestamp - timedelta(days=2)) for i in range(7)]
    db.add_all(rows)
    db.commit()
    with Session(engine) as busy:
        busy.scalar(select(GitHubLoginState).where(GitHubLoginState.id == rows[0].id).with_for_update())
        assert cleanup_login_states(db, timestamp, batch_size=2) == 2
        db.commit()
        assert db.get(GitHubLoginState, rows[0].id) is not None
        assert len(db.scalars(select(GitHubLoginState)).all()) == 5
    assert cleanup_login_states(db, timestamp, batch_size=2) == 2
    db.commit()
    assert len(db.scalars(select(GitHubLoginState)).all()) == 3


def test_cleanup_cannot_remove_grant_or_family_while_refresh_rotation_holds_lock(auth_db):
    db, engine, user_id, client_id = auth_db
    timestamp = instant()
    grant = OAuthGrant(client_id=client_id, user_id=user_id, params={}, consumed=True,
                       expires_at=timestamp - timedelta(days=120))
    db.add(grant)
    db.flush()
    old_refresh = credential(user_id, timestamp - timedelta(days=100), grant_id=grant.id, kind="refresh")
    db.add(old_refresh)
    db.commit()
    with Session(engine) as rotating:
        rotating.scalar(select(OAuthGrant).where(OAuthGrant.id == grant.id).with_for_update())
        assert cleanup_credentials(db, timestamp) == 0
        assert cleanup_grants(db, timestamp) == 0
        db.commit()
        rotating.add(credential(user_id, timestamp + timedelta(days=30), grant_id=grant.id, kind="refresh"))
        rotating.commit()
    assert cleanup_credentials(db, timestamp) == 0
    assert cleanup_grants(db, timestamp) == 0
    db.commit()
    assert db.get(OAuthGrant, grant.id) is not None
    assert db.get(ApiCredential, old_refresh.id) is not None


def test_sweep_commits_each_class_against_postgresql(auth_db, monkeypatch):
    from computeforgood import auth_retention
    db, engine, user_id, _ = auth_db
    timestamp = instant()
    db.add(GitHubLoginState(id=uuid.uuid4().hex, cookie_hash="test-only", verifier="test-only",
                            expires_at=timestamp - timedelta(days=2)))
    db.add(BrowserSession(user_id=user_id, token_hash=uuid.uuid4().hex,
                          expires_at=timestamp - timedelta(days=31)))
    db.add(credential(user_id, timestamp - timedelta(days=91)))
    db.commit()
    monkeypatch.setattr(auth_retention, "SessionLocal", sessionmaker(engine))
    counts = auth_retention.sweep_auth_retention()
    assert counts == {"cleanup_login_states": 1, "cleanup_browser_sessions": 1,
                      "cleanup_credentials": 1, "cleanup_grants": 0}
    db.expire_all()
    for model in (GitHubLoginState, BrowserSession, ApiCredential):
        assert db.scalars(select(model.id)).all() == []
