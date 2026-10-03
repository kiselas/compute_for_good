"""Maintainer planning invariants over HTTP and isolated PostgreSQL fixtures.

The shared fixtures refuse non-demo backends. Every project here has a unique
QA URL and owner; existing showcase/production records are never modified.
"""
from types import SimpleNamespace
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid

import pytest
import httpx
from sqlalchemy import insert, select, update

from test_http_alpha import claim, review, signed_webhook, submit
from test_transports import rpc_json
from computeforgood.auth import csrf_token

BASE = '/api/maintainer'


def result(response):
    assert response.status_code in (200, 201), response.text
    return response.json()


def goal_body(**changes):
    body = dict(title='Reduce regressions in repository changes',
                description='Create independently verifiable contribution contracts', priority=3)
    body.update(changes)
    return body


def improvement_body(**changes):
    body = dict(title='Cover the missing regression scenario',
                problem='The current tests do not protect this observable behavior',
                outcome='A failing regression becomes a repeatable verified check',
                acceptance_criteria=['The regression fails before the fix and passes after it'],
                in_scope='Isolated tests and the minimal correction',
                out_of_scope='Infrastructure, secrets and unrelated refactoring',
                kind='TESTS', priority=3)
    body.update(changes)
    return body


def task_body(**changes):
    body = dict(title='Add an isolated regression test',
                description='Exercise the externally observable failing case',
                difficulty='EASY', risk='LOW', required_model_tier='BASIC',
                estimated_minutes=15,
                acceptance_criteria=['The isolated regression assertion passes'],
                allowed_paths=['tests/**'], forbidden_paths=['secrets/**'],
                verification_commands=['pytest tests/test_regression.py'])
    body.update(changes)
    return body


@contextmanager
def mcp_session(api, actor):
    with httpx.Client(base_url=str(api.base_url), timeout=20, follow_redirects=True, trust_env=False) as client:
        headers = {**actor.headers, 'Accept': 'application/json, text/event-stream'}
        response = client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'cfg-maintainer-qa', 'version': '1'},
            },
        })
        initialized = rpc_json(response, 1)
        headers['MCP-Protocol-Version'] = initialized['protocolVersion']
        if response.headers.get('mcp-session-id'):
            headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
        notification = client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        assert notification.status_code in (200, 202, 204), notification.text
        request_id = 1

        def call(name, arguments):
            nonlocal request_id
            request_id += 1
            return rpc_json(client.post('/mcp', headers=headers, json={
                'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call',
                'params': {'name': name, 'arguments': arguments},
            }), request_id)
        yield call


def browser_actor(database, actors, actor):
    # Use a genuine non-demo browser owner, rather than legacy demo-token powers.
    actors.scoped_credential(actor, ['work:read', 'work:write'])
    raw = 'qa-browser-' + uuid.uuid4().hex
    with database.engine.begin() as connection:
        connection.execute(insert(database.table('browser_sessions')).values(
            id=str(uuid.uuid4()), user_id=actor.id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            created_at=datetime.now(timezone.utc),
        ))
    return SimpleNamespace(id=actor.id,
                           headers={'Cookie': 'cfg_session=' + raw, 'X-CSRF-Token': csrf_token(raw)})


@pytest.fixture
def planning(api, database, actors, qa_project):
    owner = browser_actor(database, actors, actors.author)
    outsider = browser_actor(database, actors, actors.create('contributor'))
    def project(owner=None, status='VERIFIED'):
        row = dict(qa_project, id=str(uuid.uuid4()),
                   slug=qa_project['slug'] + '-plan-' + uuid.uuid4().hex[:8],
                   repository_url='https://github.com/cfg-alpha-test/' + uuid.uuid4().hex,
                   maintainer_id=(owner or actors.author).id, status=status)
        with database.engine.begin() as connection:
            connection.execute(insert(database.table('projects')).values(**row))
        return row

    own = project()

    def post_goal(project_id=None, headers=None, **body):
        return result(api.post(f'{BASE}/projects/{project_id or own["id"]}/goals',
                               json=goal_body(**body), headers=headers or owner.headers))

    def propose(project_id=None, headers=None, **body):
        return result(api.post(f'{BASE}/projects/{project_id or own["id"]}/improvements',
                               json=improvement_body(**body), headers=headers or owner.headers))

    def draft(improvement, headers=None, **body):
        return result(api.post(f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}/tasks',
                               json=task_body(**body), headers=headers or owner.headers))

    def approve(improvement):
        return result(api.patch(f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}',
                                json={'version': improvement['version'], 'status': 'APPROVED'},
                                headers=owner.headers))

    def publish(task):
        return result(api.post(f'{BASE}/projects/{task["project_id"]}/tasks/{task["id"]}/publish',
                               json={'version': task['version']}, headers=owner.headers))

    return SimpleNamespace(project=own, owner=owner, outsider=outsider, make_project=project, goal=post_goal,
                           propose=propose, draft=draft, approve=approve, publish=publish)


def test_owner_plan_is_private_and_candidate_can_prepare_but_not_dispatch(api, actors, planning):
    owned = result(api.get(f'{BASE}/projects', headers=planning.owner.headers))
    assert planning.project['id'] in {row['id'] for row in owned}
    assert api.get(f'{BASE}/projects/{planning.project["id"]}/plan', headers=planning.outsider.headers).status_code == 404
    foreign_projects = result(api.get(f'{BASE}/projects', headers=planning.outsider.headers))
    assert planning.project['id'] not in {row['id'] for row in foreign_projects}
    candidate = planning.make_project(status='CANDIDATE')
    goal = planning.goal(project_id=candidate['id'])
    improvement = planning.propose(project_id=candidate['id'], goal_id=goal['id'])
    task = planning.draft(improvement)
    assert task['status'] == 'DRAFT'
    assert task['improvement_id'] == improvement['id']
    assert api.get(f'/api/tasks/{task["id"]}').status_code == 404
    assert api.get(f'/api/tasks/{task["id"]}', headers=planning.outsider.headers).status_code == 404
    assert task['id'] not in {row['id'] for row in result(api.get('/api/tasks', params={'project_id': candidate['id']}))}
    with mcp_session(api, actors.reviewers[0]) as call:
        denied = call('get_work_context', {'task_id': task['id']})
        assert denied.get('isError') is True
        assert 'CFG_404' in json.dumps(denied)
    planning.approve(improvement)
    assert api.post(f'{BASE}/projects/{task["project_id"]}/tasks/{task["id"]}/publish', json={'version': task['version']}, headers=planning.owner.headers).status_code == 403
    assert api.post(f'/api/tasks/{task["id"]}/claim', json={}, headers=actors.reviewers[0].headers).status_code in (403, 409)
    snapshot = result(api.get(f'{BASE}/projects/{candidate["id"]}/plan', headers=planning.owner.headers))
    assert snapshot['project']['status'] == 'CANDIDATE'
    assert task['id'] in {row['id'] for row in snapshot['tasks']}


def test_proposed_improvement_requires_human_approval_before_publication(api, actors, planning):
    improvement = planning.propose()
    task = planning.draft(improvement)
    assert improvement['status'] == 'PROPOSED' and task['status'] == 'DRAFT'
    assert task['contract_locked'] is False
    assert api.post(f'{BASE}/projects/{task["project_id"]}/tasks/{task["id"]}/publish', json={'version': task['version']}, headers=planning.owner.headers).status_code == 403
    assert api.post(f'/api/tasks/{task["id"]}/claim', json={}, headers=actors.reviewers[0].headers).status_code in (403, 409)
    planning.approve(improvement)
    published = planning.publish(task)
    assert published['status'] == 'AVAILABLE'
    assert api.post(f'{BASE}/projects/{task["project_id"]}/tasks/{task["id"]}/publish', json={'version': task['version']}, headers=planning.owner.headers).status_code == 409
    assert claim(api, published, actors.reviewers[0])['status'] == 'ACTIVE'


def test_goal_pause_withdraws_unclaimed_work_and_preserves_active_heartbeat(api, actors, planning):
    goal = planning.goal()
    improvement = planning.propose(goal_id=goal['id'])
    available, active = planning.draft(improvement), planning.draft(improvement)
    planning.approve(improvement)
    available, active = planning.publish(available), planning.publish(active)
    lease = claim(api, active, actors.reviewers[0])
    paused = result(api.patch(f'{BASE}/projects/{goal["project_id"]}/goals/{goal["id"]}', json={'version': goal['version'], 'status': 'PAUSED'}, headers=planning.owner.headers))
    assert paused['status'] == 'PAUSED'
    assert result(api.get(f'/api/tasks/{available["id"]}', headers=planning.owner.headers))['status'] == 'DRAFT'
    assert api.post(f'/api/tasks/{available["id"]}/claim', json={}, headers=actors.reviewers[1].headers).status_code in (403, 409)
    heartbeat = api.post(f'/api/leases/{lease["id"]}/heartbeat', json={'token': lease['token']}, headers=actors.reviewers[0].headers)
    assert heartbeat.status_code == 200, heartbeat.text
    assert result(api.get(f'/api/tasks/{active["id"]}', headers=actors.reviewers[0].headers))['status'] == 'IN_PROGRESS'
    assert api.post(f'{BASE}/projects/{available["project_id"]}/tasks/{available["id"]}/publish', json={'version': result(api.get(f'/api/tasks/{available["id"]}', headers=planning.owner.headers))['version']}, headers=planning.owner.headers).status_code == 403


def test_versions_prevent_overwriting_concurrent_planning_edits(api, actors, planning):
    goal = planning.goal()
    improvement = planning.propose(goal_id=goal['id'])
    task = planning.draft(improvement)
    for resource, row in [('goals', goal), ('improvements', improvement), ('tasks', task)]:
        path = f'{BASE}/projects/{row["project_id"]}/{resource}/{row["id"]}'
        edited = result(api.patch(path, json={'version': row['version'], 'title': 'Human approved revised contract title'}, headers=planning.owner.headers))
        assert edited['version'] > row['version']
        stale = api.patch(path, json={'version': row['version'], 'title': 'Stale edit must never overwrite the current version'}, headers=planning.owner.headers)
        assert stale.status_code == 409, stale.text


@pytest.mark.parametrize('changes', [
    {'title': '   '}, {'description': '   '}, {'acceptance_criteria': ['   ']},
    {'verification_commands': ['   ']}, {'verification_commands': []},
    {'allowed_paths': []},
    {'risk': 'HIGH', 'required_model_tier': 'STRONG'},
])
def test_task_contract_rejects_blank_entries_and_below_risk_model(api, actors, planning, changes):
    improvement = planning.propose()
    rejected = api.post(f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}/tasks', json=task_body(**changes), headers=planning.owner.headers)
    assert rejected.status_code == 422, rejected.text


def test_historically_acquired_contract_stays_frozen_after_release(api, actors, planning):
    goal = planning.goal()
    improvement = planning.propose(goal_id=goal['id'])
    task = planning.draft(improvement)
    planning.approve(improvement)
    task = planning.publish(task)
    lease = claim(api, task, actors.reviewers[0])
    result(api.post(f'/api/leases/{lease["id"]}/release', json={'token': lease['token']}, headers=actors.reviewers[0].headers))
    current = result(api.get(f'/api/tasks/{task["id"]}', headers=planning.owner.headers))
    assert current['contract_locked'] is True
    rejected = api.patch(f'{BASE}/projects/{task["project_id"]}/tasks/{task["id"]}', json={'version': current['version'], 'acceptance_criteria': ['A different contract must not replace acquired work']}, headers=planning.owner.headers)
    assert rejected.status_code == 409, rejected.text
    for resource, row, changes in [
        ('goals', goal, {'title': 'A different goal invalidates the acquired contract'}),
        ('improvements', improvement, {'problem': 'Replace the acquired work problem statement'}),
    ]:
        snapshot = result(api.get(f'{BASE}/projects/{planning.project["id"]}/plan', headers=planning.owner.headers))
        current_parent = next(item for item in snapshot[resource] if item['id'] == row['id'])
        rejected = api.patch(f'{BASE}/projects/{row["project_id"]}/{resource}/{row["id"]}', json={'version': current_parent['version'], **changes}, headers=planning.owner.headers)
        assert rejected.status_code == 409, rejected.text


def test_cross_project_parent_links_and_foreign_improvement_are_rejected(api, actors, planning):
    other = planning.make_project()
    foreign_goal = planning.goal(project_id=other['id'])
    rejected = api.post(f'{BASE}/projects/{planning.project["id"]}/improvements', json=improvement_body(goal_id=foreign_goal['id']), headers=planning.owner.headers)
    assert rejected.status_code == 404, rejected.text
    improvement = planning.propose()
    rejected = api.patch(f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}', json={'version': improvement['version'], 'goal_id': foreign_goal['id']}, headers=planning.owner.headers)
    assert rejected.status_code == 404, rejected.text
    assert api.post(f'{BASE}/projects/{other["id"]}/improvements/{improvement["id"]}/tasks', json=task_body(), headers=planning.owner.headers).status_code == 404
    assert api.post(f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}/tasks', json=task_body(), headers=planning.outsider.headers).status_code == 404


def test_work_write_scope_does_not_grant_maintainer_planning(api, actors, planning):
    owner = actors.author
    rejected = api.post(f'{BASE}/projects/{planning.project["id"]}/improvements', json=improvement_body(), headers=owner.headers)
    assert rejected.status_code == 403, rejected.text
    with mcp_session(api, owner) as call:
        denied = call('get_project_plan', {'project_id': planning.project['id']})
        assert denied.get('isError') is True
        assert 'CFG_403' in json.dumps(denied)


def test_project_plan_scope_can_prepare_drafts_but_cannot_approve_or_publish(api, database, actors, planning):
    goal = planning.goal()
    owner = actors.author
    credentials = database.table('api_credentials')
    with database.engine.begin() as connection:
        connection.execute(update(credentials).where(credentials.c.user_id == owner.id).values(scopes=['work:read', 'project:plan']))
    improvement = planning.propose(goal_id=goal['id'], headers=owner.headers)
    task = planning.draft(improvement, headers=owner.headers)
    assert task['status'] == 'DRAFT'
    assert api.patch(f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}', json={'version': improvement['version'], 'status': 'APPROVED'}, headers=owner.headers).status_code == 403
    assert api.post(f'{BASE}/projects/{task["project_id"]}/tasks/{task["id"]}/publish', json={'version': task['version']}, headers=owner.headers).status_code == 403
    with mcp_session(api, owner) as call:
        assert call('get_project_plan', {'project_id': planning.project['id']}).get('isError', False) is False
        title = 'Isolated MCP proposal ' + uuid.uuid4().hex[:8]
        proposed = call('propose_improvement', dict(improvement_body(title=title), project_id=planning.project['id']))
        assert proposed.get('isError', False) is False
        snapshot = result(api.get(f'{BASE}/projects/{planning.project["id"]}/plan', headers=planning.owner.headers))
        created = next(row for row in snapshot['improvements'] if row['title'] == title)
        assert created['status'] == 'PROPOSED'
        drafted = call('draft_task', dict(task_body(), project_id=planning.project['id'], improvement_id=created['id']))
        assert drafted.get('isError', False) is False
        snapshot = result(api.get(f'{BASE}/projects/{planning.project["id"]}/plan', headers=planning.owner.headers))
        assert any(row['improvement_id'] == created['id'] and row['status'] == 'DRAFT' for row in snapshot['tasks'])


def test_default_personal_credential_does_not_grant_project_planning(api, planning):
    credential = result(api.post('/api/credentials', json={'name': 'QA default credential'}, headers=planning.owner.headers))
    assert sorted(credential['scopes']) == ['work:read', 'work:write']
    assert 'project:plan' not in credential['scopes']
    explicit = result(api.post('/api/credentials', json={'name': 'QA explicit planning credential', 'scopes': ['work:read', 'project:plan']}, headers=planning.owner.headers))
    assert sorted(explicit['scopes']) == ['project:plan', 'work:read']


def test_done_requires_a_merge_and_no_unfinished_children(api, actors, planning):
    improvement = planning.propose()
    path = f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}'
    assert api.patch(path, json={'version': improvement['version'], 'status': 'DONE'}, headers=planning.owner.headers).status_code == 409
    merged_task, remaining = planning.draft(improvement), planning.draft(improvement)
    planning.approve(improvement)
    merged_task, remaining = planning.publish(merged_task), planning.publish(remaining)
    contributor = actors.create('contributor')
    submission = submit(api, dict(merged_task, _repository_url=planning.project['repository_url']), contributor)
    assert review(api, submission, actors.reviewers[0]).status_code == 200
    # Browser maintainer must see evidence for acceptance. Prospective agent
    # reviewers retain blindness even if their credential belongs to the owner.
    owner_view = result(api.get(f'/api/submissions/{submission["id"]}', headers=planning.owner.headers))
    assert owner_view['reviews'] and owner_view['quorum']['passed'] is True
    owner_agent = result(api.get(f'/api/submissions/{submission["id"]}', headers=actors.author.headers))
    assert owner_agent['reviews'] == [] and owner_agent['quorum']['blind'] is True
    review_id = owner_view['reviews'][0]['id']
    assert api.get(f'/api/reviews/{review_id}/finding-resolutions', headers=planning.owner.headers).status_code == 200
    assert api.get(f'/api/reviews/{review_id}/finding-resolutions', headers=actors.author.headers).status_code == 403
    foreign_view = result(api.get(f'/api/submissions/{submission["id"]}', headers=actors.reviewers[1].headers))
    assert foreign_view['reviews'] == [] and foreign_view['quorum']['blind'] is True
    result(api.post(f'/api/demo/submissions/{submission["id"]}/merge', json={}, headers=actors.admin.headers))
    snapshot = result(api.get(f'{BASE}/projects/{planning.project["id"]}/plan', headers=planning.owner.headers))
    assert any(row['id'] == submission['id'] for row in snapshot['submissions'])
    current = next(row for row in snapshot['improvements'] if row['id'] == improvement['id'])
    current = result(api.patch(path, json={'version': current['version'], 'status': 'ACCEPTANCE'}, headers=planning.owner.headers))
    assert api.patch(path, json={'version': current['version'], 'status': 'DONE'}, headers=planning.owner.headers).status_code == 409
    result(api.post(f'/api/admin/tasks/{remaining["id"]}/invalidate', json={'reason': 'The remaining isolated QA child is deliberately cancelled'}, headers=actors.admin.headers))
    done = result(api.patch(path, json={'version': current['version'], 'status': 'DONE'}, headers=planning.owner.headers))
    assert done['status'] == 'DONE'


def test_done_rejects_all_terminal_children_when_none_has_merged(api, actors, planning):
    improvement = planning.propose()
    task = planning.draft(improvement)
    planning.approve(improvement)
    task = planning.publish(task)
    result(api.post(f'/api/admin/tasks/{task["id"]}/invalidate', json={'reason': 'QA cancellation cannot be counted as completed improvement impact'}, headers=actors.admin.headers))
    snapshot = result(api.get(f'{BASE}/projects/{planning.project["id"]}/plan', headers=planning.owner.headers))
    current = next(row for row in snapshot['improvements'] if row['id'] == improvement['id'])
    current = result(api.patch(f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}', json={'version': current['version'], 'status': 'ACCEPTANCE'}, headers=planning.owner.headers))
    rejected = api.patch(f'{BASE}/projects/{improvement["project_id"]}/improvements/{improvement["id"]}', json={'version': current['version'], 'status': 'DONE'}, headers=planning.owner.headers)
    assert rejected.status_code == 409, rejected.text


def test_signed_synchronize_cannot_resurrect_operator_invalidated_submission(api, actors, make_task, database):
    task = make_task()
    submission = submit(api, task, actors.author)
    result(api.post(f'/api/admin/tasks/{task["id"]}/invalidate', json={'reason': 'Independent audit found this canonical submission unsuitable'}, headers=actors.admin.headers))
    response = signed_webhook(api, submission, sha='b' * 40)
    assert response.status_code == 200, response.text
    current = result(api.get(f'/api/submissions/{submission["id"]}', headers=actors.admin.headers))
    assert current['status'] == 'INVALID'
    assert current['head_sha'] == submission['head_sha']
    assert result(api.get(f'/api/tasks/{task["id"]}'))['status'] == 'INVALID'
    items = database.table('review_work_items')
    with database.engine.connect() as connection:
        statuses = connection.scalars(select(items.c.status).where(items.c.submission_id == submission['id'])).all()
    assert statuses and all(status == 'STALE' for status in statuses)
