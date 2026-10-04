"""Current-source authorization and bounded PostgreSQL request regressions."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import importlib
import time
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from computeforgood.models import ApiCredential, BrowserSession, Lease, Task
from computeforgood.services import hash_token
from test_http_alpha import submit
from test_review_workflow import leased_review, reserve
from test_work_discovery import discovery_client, mcp_call


@pytest.fixture
def source_client(database, monkeypatch):
    module = importlib.import_module('computeforgood.app')
    runtime = importlib.import_module('computeforgood.db')
    # Use the actual configured runtime engine so this assertion cannot pass
    # merely by duplicating the timeout configuration inside a test fixture.
    assert runtime.engine.url.port == database.engine.url.port
    factory = sessionmaker(runtime.engine, expire_on_commit=False)
    monkeypatch.setattr(module, 'SessionLocal', factory)
    # These checks exercise REST only. The separate discovery fixture creates a
    # fresh MCP manager; starting the original one repeatedly is unsupported.
    monkeypatch.setattr(module, 'mcp_app', None)
    with factory() as db:
        assert db.scalar(text('SHOW statement_timeout')) == '10s'
        assert db.scalar(text('SHOW lock_timeout')) == '3s'
    with TestClient(module.api) as client:
        yield client, factory


def operator_pat(database, actor):
    token = 'qa-scoped-operator-' + uuid.uuid4().hex
    with database.engine.begin() as connection:
        connection.execute(database.table('api_credentials').insert().values(
            id=str(uuid.uuid4()), user_id=actor.id, token_hash=hash_token(token),
            name='QA bounded operator credential', scopes=['work:read', 'work:write'],
            kind='access', expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            created_at=datetime.now(timezone.utc),
        ))
    return {'Authorization': 'Bearer ' + token}


@pytest.mark.parametrize('demo_operator', [True, False])
def test_scoped_operator_cannot_see_blind_conclusions_or_adjudicate(
    api, database, make_task, actors, discovery_client, demo_operator,
):
    client, factory = discovery_client
    operator = actors.create('operator')
    if not demo_operator:
        from sqlalchemy import update
        with database.engine.begin() as connection:
            users = database.table('users')
            connection.execute(update(users).where(users.c.id == operator.id).values(is_demo=False))
    headers = operator_pat(database, operator)
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    lease = reserve(api, submission, actors.reviewers[0])
    reviewed = leased_review(api, submission, actors.reviewers[0], lease,
                            decision='BLOCK', findings=[{'severity': 'HIGH', 'description': 'Private blind QA finding'}])
    assert reviewed.status_code == 200, reviewed.text
    finding_id = reviewed.json()['id']
    body = {'head_sha': submission['head_sha'], 'evidence': 'Agent credential must not acquire operator adjudication authority'}
    path = f'/api/reviews/{finding_id}/findings/0/resolve'
    assert client.post(path, headers=headers, json=body).status_code == 403
    assert client.get(f'/api/reviews/{finding_id}/finding-resolutions', headers=headers).status_code == 403
    value = client.get('/api/submissions/' + submission['id'], headers=headers).json()
    assert value['status'] == 'REVIEWING' and value['quorum']['blind'] is True
    assert value['quorum']['approved'] == 0 and value['quorum']['blocked'] is False
    assert value['reviews'] == []
    actual_task = client.get('/api/tasks/' + submission['task_id'], headers=headers).json()
    hidden = client.get('/api/tasks', params={'project_id': actual_task['project_id'], 'status': 'CHANGES_NEEDED'}, headers=headers)
    assert hidden.status_code == 200
    assert submission['task_id'] not in {row['id'] for row in hidden.json()}
    assert actual_task['status'] == 'REVIEWING'
    # MCP follows the same blindness; an operator account is still allowed to
    # contribute or independently review using its work-scoped token.
    from types import SimpleNamespace
    actor = SimpleNamespace(headers=headers)
    context = mcp_call(client, actor, 'get_submission_context', {'submission_id': submission['id']})
    assert context['submission']['quorum']['blind'] is True
    assert context['submission']['reviews'] == []
    for path in ('/api/admin/users', '/api/admin/actions', '/api/admin/integrations'):
        assert client.get(path, headers=headers).status_code == 403
    # A real browser login preserves operator capabilities, including when
    # demo mode is enabled. Use only a unique QA session, never production data.
    raw_session = 'qa-browser-operator-' + uuid.uuid4().hex
    with factory.begin() as db:
        db.add(BrowserSession(user_id=operator.id, token_hash=hash_token(raw_session),
                              expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
    client.cookies.set('cfg_session', raw_session)
    browser = client.get('/api/submissions/' + submission['id']).json()
    assert browser['quorum']['blocked'] is True
    assert browser['reviews'][0]['findings'][0]['description'] == 'Private blind QA finding'
    assert client.get('/api/admin/users').status_code == 200


def test_contended_claim_is_bounded_sanitized_and_rolls_back(
    source_client, make_task, actors,
):
    client, factory = source_client
    task = make_task(description='QA private value must not appear in a PostgreSQL error response')
    with factory() as holding:
        holding.scalar(select(Task).where(Task.id == task['id']).with_for_update())
        started = time.monotonic()
        response = client.post(f"/api/tasks/{task['id']}/claim", headers=actors.author.headers)
        elapsed = time.monotonic() - started
        assert response.status_code == 503, response.text
        assert 2 <= elapsed < 8
        assert response.json() == {'detail': 'Database temporarily busy; retry later'}
        assert response.headers['retry-after'] == '3'
        assert 'QA private value' not in response.text
    with factory() as db:
        assert db.get(Task, task['id']).status == 'AVAILABLE'
        assert db.scalars(select(Lease).where(Lease.task_id == task['id'])).all() == []
    retried = client.post(f"/api/tasks/{task['id']}/claim", headers=actors.author.headers)
    assert retried.status_code == 200, retried.text
    assert retried.json()['status'] == 'ACTIVE'


@pytest.mark.parametrize('oauth_grants', [0, 12])
def test_concurrent_browser_credentials_respect_personal_token_quota(source_client, actors, oauth_grants):
    from computeforgood.auth import csrf_token
    from computeforgood.models import OAuthClient, OAuthGrant, User
    from computeforgood.oauth_provider import provider
    client, factory = source_client
    raw_session = 'qa-browser-quota-' + uuid.uuid4().hex
    owner = actors.create('contributor')
    with factory.begin() as db:
        db.get(User, owner.id).is_demo = False
        db.add(BrowserSession(user_id=owner.id, token_hash=hash_token(raw_session),
                              expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        for index in range(19):
            db.add(ApiCredential(user_id=owner.id, token_hash=hash_token(uuid.uuid4().hex),
                                  name=f'QA concurrent quota seed {index}', scopes=['work:read'],
                                  kind='access', expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        if oauth_grants:
            oauth_client = OAuthClient(id='qa-quota-oauth-' + uuid.uuid4().hex, metadata_json={})
            db.add(oauth_client)
            db.flush()
            for _ in range(oauth_grants):
                grant = OAuthGrant(client_id=oauth_client.id, user_id=owner.id,
                                   params={'scopes': ['work:read', 'work:write']}, approved=True, consumed=True,
                                   expires_at=datetime.now(timezone.utc) + timedelta(minutes=5))
                db.add(grant)
                db.flush()
                # Use the real issuer, including access+refresh lifetimes and
                # grant linkage, rather than weakening the test's token types.
                provider.issue(db, grant, ['work:read', 'work:write'])
    client.cookies.set('cfg_session', raw_session)
    headers = {'X-CSRF-Token': csrf_token(raw_session)}
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda index: client.post('/api/credentials', headers=headers,
            json={'name': f'QA concurrent account request {index}', 'scopes': ['work:read']}), range(8)))
    assert [response.status_code for response in responses].count(200) == 1
    assert [response.status_code for response in responses].count(409) == 7
    next_response = client.post('/api/credentials', headers=headers,
                               json={'name': 'QA exceeds personal token quota', 'scopes': ['work:read']})
    assert next_response.status_code == 409
    assert 'personal access token' in next_response.json()['detail']
    issued = next(response.json() for response in responses if response.status_code == 200)
    bearer = {'Authorization': 'Bearer ' + issued['token']}
    assert client.get('/api/me', headers=bearer).status_code == 200
    assert client.post('/api/tasks/missing/claim', headers=bearer).status_code == 403
    with factory() as db:
        rows = db.scalars(select(ApiCredential).where(ApiCredential.user_id == owner.id,
                          ApiCredential.revoked_at.is_(None), ApiCredential.expires_at > datetime.now(timezone.utc))).all()
        personal = [row for row in rows if row.kind == 'access' and row.grant_id is None]
        oauth = [row for row in rows if row.grant_id is not None]
        assert len(personal) == 20
        assert len(oauth) == oauth_grants * 2
        assert len([row for row in oauth if row.kind == 'access']) == oauth_grants
        assert len([row for row in oauth if row.kind == 'refresh']) == oauth_grants


def test_saturated_connection_pool_returns_bounded_503_and_recovers(
    source_client, database, make_task, actors, monkeypatch,
):
    client, _ = source_client
    runtime = importlib.import_module('computeforgood.db')
    assert runtime.engine.pool.timeout() == 3
    # Saturate only a private one-connection pool, not PostgreSQL's global
    # connection limit or the live QA application's shared pool.
    isolated = create_engine(database.engine.url, pool_size=1, max_overflow=0,
                             pool_timeout=runtime.engine.pool.timeout())
    factory = sessionmaker(isolated, expire_on_commit=False)
    monkeypatch.setattr(importlib.import_module('computeforgood.app'), 'SessionLocal', factory)
    task = make_task()
    try:
        with isolated.connect():
            started = time.monotonic()
            response = client.post(f"/api/tasks/{task['id']}/claim", headers=actors.author.headers)
            assert response.status_code == 503, response.text
            assert 2 <= time.monotonic() - started < 8
            assert response.json() == {'detail': 'Database temporarily busy; retry later'}
            assert response.headers['retry-after'] == '3'
        retried = client.post(f"/api/tasks/{task['id']}/claim", headers=actors.author.headers)
        assert retried.status_code == 200, retried.text
    finally:
        isolated.dispose()
