"""Launch-specific policy and real worker recovery checks."""
from datetime import datetime, timezone
import time
from types import SimpleNamespace
import uuid
import pytest
from sqlalchemy import insert, select, update
from computeforgood import github_checks as checks
from computeforgood.project_gateway import canonical_repo


def test_repository_application_canonicalization():
    assert canonical_repo('https://github.com/Owner/Project.git/') == 'https://github.com/owner/project'
    from fastapi import HTTPException
    for url in ['https://github.com.evil.test/a/b', 'https://user@github.com/a/b', 'http://github.com/a/b', 'https://github.com/a/b/pull/1', 'https://github.com/a/b?x=1']:
        with pytest.raises(HTTPException):
            canonical_repo(url)


@pytest.mark.parametrize('scenario,expected', [('success', True), ('missing', False), ('stale', False), ('pending', False), ('neutral', False), ('collision', False), ('no_policy', False)])
def test_ci_policy_fails_closed(monkeypatch, scenario, expected):
    from computeforgood.models import Task, Project
    task = SimpleNamespace(project_id='project', status='REVIEWING')
    project = SimpleNamespace(repository_url='https://github.com/owner/repo', required_checks=['build'] if scenario != 'no_policy' else [])
    submission = SimpleNamespace(task_id='task', id='sub', head_sha='a' * 40, is_demo=False, checks_passed=True, status='REVIEWING')
    db = SimpleNamespace(get=lambda model, id: task if model is Task else project)
    run = {'name': 'build', 'head_sha': 'a' * 40, 'status': 'completed', 'conclusion': 'success'}
    if scenario == 'stale':
        run['head_sha'] = 'b' * 40
    if scenario == 'pending':
        run['status'] = 'in_progress'
    if scenario == 'neutral':
        run['conclusion'] = 'neutral'
    def api(path):
        if '/check-runs?' in path:
            return {'check_runs': [] if scenario == 'missing' else [run]}
        return {'statuses': [{'context': 'build', 'state': 'failure'}] if scenario == 'collision' else []}
    monkeypatch.setattr(checks, 'api_json', api)
    monkeypatch.setattr(checks.s, 'quorum', lambda *args: {'blocked': False, 'passed': True})
    monkeypatch.setattr(checks.s, 'event', lambda *args: None)
    checks.reconcile(db, submission)
    assert submission.checks_passed is expected
    if scenario != 'no_policy':
        assert submission.status == ('AWAITING_MAINTAINER' if expected else 'REVIEWING')


def test_poisoned_webhook_does_not_starve_queue(api, database, actors):
    deliveries = database.table('webhook_deliveries')
    bad, good = 'qa-poison-' + uuid.uuid4().hex, 'qa-good-' + uuid.uuid4().hex
    created = datetime.now(timezone.utc)
    with database.engine.begin() as connection:
        connection.execute(insert(deliveries), [
            {'id': bad, 'event_type': 'pull_request', 'payload': {'pull_request': []}, 'status': 'PENDING', 'attempts': 0, 'created_at': created},
            {'id': good, 'event_type': 'ping', 'payload': {}, 'status': 'PENDING', 'attempts': 0, 'created_at': created},
        ])
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        with database.engine.connect() as connection:
            states = {r['id']: dict(r) for r in connection.execute(select(deliveries).where(deliveries.c.id.in_([bad, good]))).mappings()}
        if states[bad]['attempts'] >= 1 and states[good]['status'] == 'DONE':
            break
        time.sleep(.25)
    assert states[good]['status'] == 'DONE'
    assert states[bad]['status'] == 'PENDING'
    assert states[bad]['attempts'] >= 1
    assert states[bad]['next_attempt_at'] is not None
    assert states[bad]['last_attempt_at'] is not None
    assert states[bad]['error'].startswith('AttributeError:')
    # Accelerate only this isolated QA delivery to verify the final retry gate.
    with database.engine.begin() as connection:
        connection.execute(update(deliveries).where(deliveries.c.id == bad).values(attempts=7, next_attempt_at=None))
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        with database.engine.connect() as connection:
            failed = connection.execute(select(deliveries).where(deliveries.c.id == bad)).mappings().one()
        if failed['status'] == 'FAILED':
            break
        time.sleep(.25)
    assert failed['status'] == 'FAILED' and failed['attempts'] == 8
    assert api.post('/api/admin/integrations/' + bad + '/retry', json={}, headers=actors.author.headers).status_code == 403
    with database.engine.begin() as connection:
        connection.execute(update(deliveries).where(deliveries.c.id == bad).values(payload={'pull_request': {}}))
    assert api.post('/api/admin/integrations/' + bad + '/retry', json={}, headers=actors.admin.headers).status_code == 200
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        with database.engine.connect() as connection:
            recovered = connection.execute(select(deliveries).where(deliveries.c.id == bad)).mappings().one()
        if recovered['status'] == 'DONE':
            break
        time.sleep(.25)
    assert recovered['status'] == 'DONE'


@pytest.mark.parametrize('case,status', [('unlinked', 403), ('impersonation', 422), ('old_pr', 422), ('stale_sha', 422), ('valid', None)])
def test_real_pr_identity_time_and_sha_policy(monkeypatch, case, status):
    from computeforgood import services
    from fastapi import HTTPException
    project = SimpleNamespace(repository_url='https://github.com/owner/repo')
    task = SimpleNamespace(id='CFG-TEST', is_demo=False)
    user = SimpleNamespace(username='test_user', github_id=None if case == 'unlinked' else '12345')
    body = SimpleNamespace(pr_url='https://github.com/owner/repo/pull/1', head_sha='a' * 40)
    pr = {'head': {'sha': 'b' * 40 if case == 'stale_sha' else 'a' * 40}, 'state': 'open', 'title': '[CFG-TEST] Improve tests',
          'body': 'ComputeForGood-Task: CFG-TEST\nComputeForGood-Contributor: @test_user',
          'user': {'id': 99999 if case == 'impersonation' else 12345, 'login': 'test_user'},
          'created_at': '2026-10-03T00:00:00Z' if case == 'old_pr' else '2026-10-03T00:00:02Z'}
    monkeypatch.setattr(services.httpx, 'get', lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None, json=lambda: pr))
    acquired = datetime(2026, 10, 3, 0, 0, 1, 500000, tzinfo=timezone.utc)
    if status:
        with pytest.raises(HTTPException) as error:
            services.validate_pr(project, task, user, body, acquired_at=acquired)
        assert error.value.status_code == status
    else:
        assert services.validate_pr(project, task, user, body, acquired_at=acquired) is False
