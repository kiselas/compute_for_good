"""Release regressions using HTTP, PostgreSQL and a controlled GitHub boundary."""
from datetime import datetime, timezone
import importlib
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from computeforgood import github_checks as checks, services, worker
from computeforgood.models import ImpactCredit, Project, Submission, WebhookDelivery
from test_http_alpha import claim, submit
from test_review_workflow import leased_review, reserve


def test_suspended_completed_reviewer_has_same_head_replacement(api, database, make_task, actors):
    submission = submit(api, make_task(), actors.author)
    original = reserve(api, submission, actors.reviewers[0])
    assert leased_review(api, submission, actors.reviewers[0], original).status_code == 200
    suspended = api.post(f'/api/admin/users/{actors.reviewers[0].id}/suspend',
                         json={'suspended': True, 'reason': 'Isolated QA reviewer suspension'},
                         headers=actors.admin.headers)
    assert suspended.status_code == 200, suspended.text
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['head_sha'] == submission['head_sha']
    assert state['quorum']['approved'] == 0 and not state['quorum']['passed']
    assert state['status'] == 'REVIEWING'
    replacement = reserve(api, submission, actors.reviewers[1])
    assert replacement['work_item_id'] != original['work_item_id']
    assert leased_review(api, submission, actors.reviewers[1], replacement).status_code == 200
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['quorum']['passed'] and len(state['reviews']) == 2
    slots = database.table('review_work_items')
    with database.engine.connect() as connection:
        rows = connection.execute(select(slots.c.id, slots.c.status).where(
            slots.c.submission_id == submission['id'])).all()
    assert {row.id for row in rows} == {original['work_item_id'], replacement['work_item_id']}
    assert all(row.status == 'COMPLETED' for row in rows)


@pytest.mark.parametrize('decision,hidden', [('APPROVE', 'AWAITING_MAINTAINER'), ('REQUEST_CHANGES', 'CHANGES_NEEDED')])
def test_status_filter_uses_blind_state(api, database, make_task, actors, decision, hidden):
    task = make_task()
    submission = submit(api, task, actors.author)
    lease = reserve(api, submission, actors.reviewers[0])
    assert leased_review(api, submission, actors.reviewers[0], lease, decision=decision).status_code == 200
    for headers in ({}, actors.reviewers[1].headers):
        params = {'project_id': task['project_id'], 'status': hidden}
        secret = api.get('/api/tasks', params=params, headers=headers)
        assert secret.status_code == 200, secret.text
        assert task['id'] not in {row['id'] for row in secret.json()}
        params['status'] = 'REVIEWING'
        visible = api.get('/api/tasks', params=params, headers=headers)
        assert visible.status_code == 200, visible.text
        assert next(row for row in visible.json() if row['id'] == task['id'])['status'] == 'REVIEWING'
    own = api.get('/api/tasks', params={'project_id': task['project_id'], 'status': hidden}, headers=actors.author.headers)
    assert task['id'] in {row['id'] for row in own.json()}


def successful_ci(path):
    if '/check-runs?' in path:
        sha = path.split('/commits/', 1)[1].split('/', 1)[0]
        return {'check_runs': [{'name': 'build', 'head_sha': sha, 'status': 'completed', 'conclusion': 'success'}]}
    return {'statuses': [], 'total_count': 0}


def test_registration_and_revision_queue_ci_with_retry(api, database, make_task, actors, monkeypatch):
    """CI completed before registration; no additional webhook is necessary."""
    factory = sessionmaker(database.engine, expire_on_commit=False)
    app_module = importlib.import_module('computeforgood.app')
    monkeypatch.setattr(app_module, 'SessionLocal', factory)
    monkeypatch.setattr(worker, 'SessionLocal', factory)
    monkeypatch.setattr(services, 'validate_pr', lambda *args, **kwargs: False)
    enqueue = checks.enqueue_reconciliation
    # Future due times isolate this test from the actual integration worker.
    future = datetime(2100, 1, 1, tzinfo=timezone.utc)
    def deferred(db, submission):
        enqueue(db, submission)
        for row in db.new:
            if isinstance(row, WebhookDelivery) and row.event_type == 'reconcile_submission':
                row.next_attempt_at = future
                row.created_at = datetime(1990, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(checks, 'enqueue_reconciliation', deferred)
    task = make_task()
    task['_repository_url'] = 'https://github.com/cfg-alpha-test/ci-' + uuid.uuid4().hex
    # Use a separate project so policy changes cannot affect concurrent fixtures.
    with factory.begin() as db:
        project = Project(slug='qa-ci-' + uuid.uuid4().hex, name='Queue QA',
                          repository_url=task['_repository_url'], status='VERIFIED', is_demo=True,
                          description='', language='Python', required_checks=['build'])
        db.add(project)
        db.flush()
        services.get_task(db, task['id']).project_id = project.id
    lease = claim(api, task, actors.author)
    permit = api.post(f"/api/tasks/{task['id']}/permit", json={'lease_token': lease['token']}, headers=actors.author.headers)
    assert permit.status_code == 200, permit.text
    client = TestClient(app_module.api)
    registered = client.post(f"/api/tasks/{task['id']}/submissions", json={
        'permit_token': permit.json()['token'], 'pr_url': task['_repository_url'] + '/pull/' + str(int(uuid.uuid4().hex[:8], 16)),
        'head_sha': 'a' * 40, 'summary': 'CI already finished before registration',
    }, headers=actors.author.headers)
    assert registered.status_code == 200, registered.text
    submission = registered.json()
    with factory() as db:
        queued = db.scalar(select(WebhookDelivery).where(WebhookDelivery.payload['submission_id'].as_string() == submission['id']))
        assert queued is not None and queued.status == 'PENDING'
        delivery_id = queued.id
    clock = [future]
    monkeypatch.setattr(worker, 'now', lambda db: clock[0])
    monkeypatch.setattr(checks, 'api_json', lambda path: (_ for _ in ()).throw(httpx.ConnectError('controlled unavailable')))
    worker.integrations()
    with factory() as db:
        retry = db.get(WebhookDelivery, delivery_id)
        assert retry.status == 'PENDING' and retry.attempts == 1
        assert retry.next_attempt_at > future and retry.error.startswith('ConnectError:')
        assert not db.get(Submission, submission['id']).checks_passed
        clock[0] = retry.next_attempt_at
    monkeypatch.setattr(checks, 'api_json', successful_ci)
    worker.integrations()
    with factory() as db:
        assert db.get(WebhookDelivery, delivery_id).status == 'DONE'
        assert db.get(Submission, submission['id']).checks_passed
    revised = client.post(f"/api/submissions/{submission['id']}/resubmit", json={'head_sha': 'b' * 40}, headers=actors.author.headers)
    assert revised.status_code == 200, revised.text
    with factory() as db:
        jobs = db.scalars(select(WebhookDelivery).where(WebhookDelivery.payload['submission_id'].as_string() == submission['id'])).all()
        assert len(jobs) == 2
        assert sum(row.status == 'PENDING' for row in jobs) == 1
    worker.integrations()
    with factory() as db:
        current = db.get(Submission, submission['id'])
        assert current.head_sha == 'b' * 40 and current.checks_passed


@pytest.mark.parametrize('merged', [True, False])
def test_closed_before_synchronize_records_authoritative_head(api, database, make_task, actors, monkeypatch, merged):
    submission = submit(api, make_task(), actors.author)
    factory = sessionmaker(database.engine, expire_on_commit=False)
    with factory.begin() as db:
        db.get(Submission, submission['id']).is_demo = False
    monkeypatch.setattr(checks, 'current_pr', lambda *args: {'head': {'sha': 'b' * 40}, 'state': 'closed', 'merged': merged})
    monkeypatch.setattr(checks, 'api_json', lambda path: pytest.fail('Terminal decision must survive unavailable CI'))
    delivery_id = 'qa-order-' + uuid.uuid4().hex
    with factory.begin() as db:
        delivery = WebhookDelivery(id=delivery_id, event_type='pull_request', payload={
            'action': 'closed', 'pull_request': {'html_url': submission['pr_url'], 'head': {'sha': 'a' * 40}},
        })
        db.add(delivery)
        db.flush()
        services.process_delivery(db, delivery)
    # A delayed synchronize cannot revive the terminal work or duplicate credit.
    with factory.begin() as db:
        delivery = WebhookDelivery(id=delivery_id + '-late', event_type='pull_request', payload={
            'action': 'synchronize', 'pull_request': {'html_url': submission['pr_url'], 'head': {'sha': 'c' * 40}},
        })
        db.add(delivery)
        db.flush()
        services.process_delivery(db, delivery)
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['head_sha'] == 'b' * 40
    assert state['status'] == ('MERGED' if merged else 'CLOSED')
    with factory() as db:
        credits = db.scalars(select(ImpactCredit).where(ImpactCredit.submission_id == submission['id'])).all()
        assert len(credits) == int(merged)


@pytest.mark.parametrize('scenario', ['hidden_failure', 'incomplete', 'unbounded'])
def test_ci_status_pagination_fails_closed(api, database, make_task, actors, monkeypatch, scenario):
    submission = submit(api, make_task(), actors.author)
    factory = sessionmaker(database.engine, expire_on_commit=False)
    paths = []
    def github(path):
        paths.append(path)
        if '/check-runs?' in path:
            return successful_ci(path)
        if scenario == 'incomplete':
            return {'total_count': 101, 'statuses': []}
        if '&page=1' in path or scenario == 'unbounded':
            return {'total_count': 101 if scenario != 'unbounded' else 1001,
                    'statuses': [{'context': 'context-' + str(index), 'state': 'success'} for index in range(100)]}
        return {'total_count': 101, 'statuses': [{'context': 'build', 'state': 'failure'}]}
    monkeypatch.setattr(checks, 'api_json', github)
    with factory.begin() as db:
        row = db.get(Submission, submission['id'])
        row.is_demo = False
        project = db.get(Project, services.get_task(db, row.task_id).project_id)
        # Restore the shared fixture policy inside the transaction afterward.
        old = project.required_checks
        project.required_checks = ['build']
        if scenario == 'hidden_failure':
            checks.reconcile(db, row)
            assert not row.checks_passed
            assert any('/status?' in path and 'page=2' in path for path in paths)
        else:
            with pytest.raises(ValueError):
                checks.reconcile(db, row)
            assert not row.checks_passed
        project.required_checks = old
