"""Discovery regressions on real PostgreSQL through REST and the MCP transport."""
from datetime import datetime, timedelta, timezone
import importlib
import json
import uuid

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import delete
from sqlalchemy.orm import sessionmaker

from computeforgood.models import (
    FindingResolution, Improvement, Project, ProjectGoal, Review, ReviewWorkItem, Submission, Task,
)
from test_transports import rpc_json


@pytest.fixture
def discovery_client(database, monkeypatch):
    """Run current source against the isolated QA database, not an old image."""
    factory = sessionmaker(database.engine, expire_on_commit=False)
    for name in ('app', 'mcp_gateway', 'oauth_provider'):
        module = importlib.import_module('computeforgood.' + name)
        monkeypatch.setattr(module, 'SessionLocal', factory)
    # The SDK session manager has a one-shot lifetime. Each test needs a fresh
    # mounted transport while retaining the real REST dependency graph.
    app_module = importlib.import_module('computeforgood.app')
    mcp_app = importlib.import_module('computeforgood.mcp_gateway').create_mcp_app()
    monkeypatch.setattr(app_module, 'mcp_app', mcp_app)
    mount = next(route for route in app_module.api.routes if getattr(route, 'path', None) == '/mcp')
    monkeypatch.setattr(mount, 'app', mcp_app)
    with TestClient(app_module.api, base_url='http://127.0.0.1:8110') as client:
        yield client, factory


def mcp_call(client, actor, tool, arguments):
    headers = {**actor.headers, 'Accept': 'application/json, text/event-stream'}
    response = client.post('/mcp/', headers=headers, json={
        'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {},
            'clientInfo': {'name': 'qa-work-discovery', 'version': '1.0'},
        },
    })
    initialized = rpc_json(response, 1)
    headers['MCP-Protocol-Version'] = initialized['protocolVersion']
    if response.headers.get('mcp-session-id'):
        headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
    notified = client.post('/mcp/', headers=headers, json={
        'jsonrpc': '2.0', 'method': 'notifications/initialized',
    })
    assert notified.status_code in (200, 202, 204), notified.text
    result = rpc_json(client.post('/mcp/', headers=headers, json={
        'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
        'params': {'name': tool, 'arguments': arguments},
    }), 2)
    assert not result.get('isError'), result
    if 'structuredContent' in result:
        return result['structuredContent']
    return json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))


@pytest.fixture
def discovery_fixtures(discovery_client, run_id):
    _, factory = discovery_client
    key = run_id + '-discovery-' + uuid.uuid4().hex[:8]
    with factory.begin() as db:
        project = Project(slug=key, name=key, repository_url='https://github.com/cfg-alpha-test/' + key,
                          language=key, status='VERIFIED', is_demo=True, impact_score=100)
        db.add(project)
        db.flush()
        project_id = project.id
    yield factory, project_id, key
    # These fixtures sort before the normal catalog. Remove only this test's rows
    # so later discovery checks cannot be crowded out by our intentionally old data.
    with factory.begin() as db:
        tasks = db.query(Task.id).filter(Task.project_id == project_id).subquery()
        submissions = db.query(Submission.id).filter(Submission.task_id.in_(tasks.select())).subquery()
        reviews = db.query(Review.id).filter(Review.submission_id.in_(submissions.select())).subquery()
        db.execute(delete(FindingResolution).where(FindingResolution.review_id.in_(reviews.select())))
        db.execute(delete(Review).where(Review.submission_id.in_(submissions.select())))
        db.execute(delete(ReviewWorkItem).where(ReviewWorkItem.submission_id.in_(submissions.select())))
        db.execute(delete(Submission).where(Submission.task_id.in_(tasks.select())))
        db.execute(delete(Task).where(Task.project_id == project_id))
        db.execute(delete(Improvement).where(Improvement.project_id == project_id))
        db.execute(delete(ProjectGoal).where(ProjectGoal.project_id == project_id))
        db.execute(delete(Project).where(Project.id == project_id))


def task(db, project_id, index, **overrides):
    fields = dict(project_id=project_id, title='Isolated discovery task', is_demo=True,
                  created_at=datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=index))
    fields.update(overrides)
    row = Task(**fields)
    db.add(row)
    db.flush()
    return row


def submission(db, project_id, index, author, *, risk='LOW', available=True):
    work = task(db, project_id, index, risk=risk, status='REVIEWING')
    # Equal timestamps force the keyset tie-breaker to cross the chunk boundary.
    row = Submission(id=f'{index:04d}-' + uuid.uuid4().hex,
                     task_id=work.id, author_id=author.id, is_demo=True, head_sha='a' * 40,
                     pr_url='https://github.com/cfg-alpha-test/discovery/pull/' + uuid.uuid4().hex,
                     created_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
    db.add(row)
    db.flush()
    item = ReviewWorkItem(id=f'{index:04d}-' + uuid.uuid4().hex,
                          submission_id=row.id, head_sha=row.head_sha, slot_index=0,
                          status='AVAILABLE' if available else 'CLAIMED', created_at=row.created_at)
    db.add(item)
    return row


def test_mcp_find_work_filters_tier_and_dispatch_before_limit(discovery_client, discovery_fixtures, actors):
    client, _ = discovery_client
    factory, project_id, language = discovery_fixtures
    with factory.begin() as db:
        paused = ProjectGoal(project_id=project_id, title='Paused QA goal', status='PAUSED')
        db.add(paused)
        db.flush()
        improvement = Improvement(project_id=project_id, goal_id=paused.id, title='Approved but paused',
                                  problem='QA', outcome='QA', status='APPROVED')
        db.add(improvement)
        db.flush()
        for index in range(120):
            task(db, project_id, index, required_model_tier='FRONTIER')
            task(db, project_id, index + 120, improvement_id=improvement.id)
        expected = [task(db, project_id, index + 240).id for index in range(3)]
    result = mcp_call(client, actors.basic, 'find_work', {'languages': [language], 'limit': 2})
    assert [row['id'] for row in result['tasks']] == expected[:2]
    assert result['untrusted_content_warning']


@pytest.mark.parametrize('transport', ['rest', 'legacy-rest', 'mcp'])
def test_review_discovery_scans_past_ineligible_and_complete_work(
    discovery_client, discovery_fixtures, actors, transport,
):
    client, _ = discovery_client
    factory, project_id, _ = discovery_fixtures
    with factory.begin() as db:
        # More than the old 100-row cutoff, and more than one scan chunk of
        # passed quorums. Query predicates and authoritative quorum both matter.
        for index in range(120):
            submission(db, project_id, index, actors.author, risk='NORMAL')
            done = submission(db, project_id, index + 120, actors.author)
            db.add(Review(submission_id=done.id, reviewer_id=actors.reviewers[0].id,
                          head_sha=done.head_sha, decision='APPROVE', model_tier='BASIC'))
            submission(db, project_id, index + 240, actors.basic)
            completed = submission(db, project_id, index + 360, actors.author)
            db.add(Review(submission_id=completed.id, reviewer_id=actors.basic.id,
                          head_sha=completed.head_sha, decision='REQUEST_CHANGES', model_tier='BASIC'))
            submission(db, project_id, index + 480, actors.author, available=False)
        eligible = submission(db, project_id, 600, actors.author)
        blocked = submission(db, project_id, 601, actors.author)
        # An old unresolved severe finding blocks an otherwise approved current
        # head. A prospective reviewer must see work but no leaked conclusions.
        db.add(Review(submission_id=blocked.id, reviewer_id=actors.reviewers[0].id,
                      head_sha=blocked.head_sha, decision='APPROVE', model_tier='BASIC'))
        db.add(Review(submission_id=blocked.id, reviewer_id=actors.reviewers[1].id,
                      head_sha='b' * 40, decision='BLOCK', model_tier='BASIC',
                      findings=[{'severity': 'HIGH', 'description': 'Private historic finding'}]))
        expected = [eligible.id, blocked.id]
    if transport in {'rest', 'legacy-rest'}:
        path = '/api/review-tasks' if transport == 'rest' else '/api/review-work'
        response = client.get(path, params={'limit': 2}, headers=actors.basic.headers)
        assert response.status_code == 200, response.text
        rows = response.json()
        if transport == 'legacy-rest':
            rows = [{'submission': row} for row in rows]
    else:
        rows = mcp_call(client, actors.basic, 'find_review_work', {'limit': 2})['reviews']
    assert [row['submission']['id'] for row in rows] == expected
    for row in rows:
        assert row['submission']['quorum']['blind'] is True
        assert row['submission']['quorum']['approved'] == 0
        assert row['submission']['quorum']['blocked'] is False
        assert 'Private historic finding' not in str(row)


def test_discovery_policy_blocks_real_sensitive_work_and_demo_disabled(
    discovery_client, discovery_fixtures, actors, monkeypatch,
):
    from dataclasses import replace
    from computeforgood import review_workflow

    _, factory = discovery_client
    _, project_id, _ = discovery_fixtures
    with factory.begin() as db:
        work = task(db, project_id, 0, risk='HIGH', required_model_tier='FRONTIER', is_demo=False)
        user = db.get(importlib.import_module('computeforgood.models').User, actors.author.id)
        conditions = review_workflow.discovery_eligibility(db, user)
        from sqlalchemy import select
        assert db.scalar(select(Task.id).join(Project).where(Task.id == work.id, *conditions)) is None
        monkeypatch.setattr(review_workflow, 'settings', replace(review_workflow.settings, demo_mode=False))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            review_workflow.discovery_eligibility(db, user)
        assert error.value.status_code == 401
