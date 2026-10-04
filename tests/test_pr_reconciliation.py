"""Authoritative PR state recovery with real PostgreSQL and controlled GitHub."""
import uuid

import pytest
from sqlalchemy import select

from computeforgood import github_checks as checks, services
from computeforgood.models import ImpactCredit, Project, Review, ReviewLease, ReviewWorkItem, Submission, Task, WebhookDelivery
from test_backend_boundaries import source_client
from test_http_alpha import submit
from test_review_workflow import leased_review, reserve


def real_submission_fixture(api, make_task, actors, factory):
    registered = submit(api, make_task(risk='NORMAL'), actors.author)
    lease = reserve(api, registered, actors.reviewers[0])
    assert leased_review(api, registered, actors.reviewers[0], lease).status_code == 200
    with factory.begin() as db:
        project = Project(slug='qa-pr-state-' + uuid.uuid4().hex, name='Isolated PR state recovery',
                          repository_url='https://github.com/cfg-alpha-test/' + uuid.uuid4().hex,
                          status='VERIFIED', is_demo=True, required_checks=['build'])
        db.add(project)
        db.flush()
        row = db.get(Submission, registered['id'])
        row.is_demo = False
        row.pr_url = project.repository_url + '/pull/1'
        task = db.get(Task, row.task_id)
        task.project_id = project.id
        registered.update(pr_url=row.pr_url, repository_url=project.repository_url)
    return registered


@pytest.mark.parametrize('trigger', ['queue', 'ci-event', 'operator'])
@pytest.mark.parametrize('merged', [True, False])
def test_missing_terminal_webhook_recovers_from_current_pr(
    api, make_task, actors, source_client, monkeypatch, trigger, merged,
):
    client, factory = source_client
    original = real_submission_fixture(api, make_task, actors, factory)
    observation = {'head': {'sha': 'b' * 40}, 'state': 'closed', 'merged': merged,
                   'merged_at': '2026-10-04T09:46:03Z' if merged else None}
    monkeypatch.setattr(checks, 'current_pr', lambda *args: observation)
    monkeypatch.setattr(checks, 'api_json', lambda path: pytest.fail('Terminal observation must not depend on CI availability'))
    if trigger == 'operator':
        response = client.post(f"/api/admin/submissions/{original['id']}/refresh-checks", headers=actors.admin.headers)
        assert response.status_code == 200, response.text
    else:
        with factory.begin() as db:
            delivery = WebhookDelivery(id='qa-reconcile-state-' + uuid.uuid4().hex,
                event_type='reconcile_submission' if trigger == 'queue' else 'check_run',
                payload={'submission_id': original['id'], 'head_sha': original['head_sha']} if trigger == 'queue' else {
                    'repository': {'html_url': original['repository_url']},
                    'check_run': {'head_sha': original['head_sha']},
                })
            db.add(delivery)
            db.flush()
            services.process_delivery(db, delivery)
            assert delivery.status == 'DONE' and delivery.attempts == 1
    # A delayed or repeated event must neither replace this terminal head nor
    # award another credit. Existing completed review history stays immutable.
    with factory.begin() as db:
        late = WebhookDelivery(id='qa-late-pr-' + uuid.uuid4().hex, event_type='pull_request', payload={
            'action': 'synchronize', 'pull_request': {'html_url': original['pr_url'], 'head': {'sha': 'c' * 40}},
        })
        db.add(late)
        db.flush()
        services.process_delivery(db, late)
    with factory() as db:
        row = db.get(Submission, original['id'])
        assert row.head_sha == 'b' * 40 and row.status == ('MERGED' if merged else 'CLOSED')
        assert db.get(Task, row.task_id).status == row.status
        assert row.checks_passed is False  # Old-head CI must not transfer to the current head.
        assert len(db.scalars(select(ImpactCredit).where(ImpactCredit.submission_id == row.id)).all()) == int(merged)
        assert len(db.scalars(select(Review).where(Review.submission_id == row.id)).all()) == 1
        assert not db.scalars(select(ReviewLease).where(ReviewLease.submission_id == row.id, ReviewLease.status == 'ACTIVE')).all()
        assert not db.scalars(select(ReviewWorkItem).where(ReviewWorkItem.submission_id == row.id,
                              ReviewWorkItem.status.in_(['AVAILABLE', 'CLAIMED']))).all()


@pytest.mark.parametrize('malformed', ['missing_timestamp', 'missing_head', 'inconsistent_open_merge'])
def test_incomplete_merge_observation_fails_closed_and_preserves_old_head(
    api, make_task, actors, source_client, monkeypatch, malformed,
):
    client, factory = source_client
    original = real_submission_fixture(api, make_task, actors, factory)
    observation = {'head': {'sha': 'b' * 40}, 'state': 'closed', 'merged': True,
                   'merged_at': '2026-10-04T09:46:03Z'}
    if malformed == 'missing_timestamp':
        observation.pop('merged_at')
    elif malformed == 'missing_head':
        observation['head'] = {}
    else:
        observation['state'] = 'open'
    monkeypatch.setattr(checks, 'current_pr', lambda *args: observation)
    monkeypatch.setattr(checks, 'api_json', lambda path: pytest.fail('Malformed observation cannot establish CI'))
    response = client.post(f"/api/admin/submissions/{original['id']}/refresh-checks", headers=actors.admin.headers)
    assert response.status_code == 503, response.text
    with factory() as db:
        row = db.get(Submission, original['id'])
        assert row.head_sha == original['head_sha'] and row.status == 'REVIEWING'
        assert not db.scalars(select(ImpactCredit).where(ImpactCredit.submission_id == row.id)).all()


@pytest.mark.parametrize('trigger', ['queue', 'new-head-ci', 'operator'])
def test_missing_synchronize_resets_reviews_and_checks_only_current_head(
    api, make_task, actors, source_client, monkeypatch, trigger,
):
    client, factory = source_client
    original = real_submission_fixture(api, make_task, actors, factory)
    interrupted = reserve(api, original, actors.reviewers[1])
    monkeypatch.setattr(checks, 'current_pr', lambda *args: {
        'head': {'sha': 'b' * 40}, 'state': 'open', 'merged': False,
    })
    paths = []
    def successful_ci(path):
        paths.append(path)
        assert '/commits/' + 'b' * 40 + '/' in path
        if '/check-runs?' in path:
            return {'check_runs': [{'name': 'build', 'head_sha': 'b' * 40, 'status': 'completed', 'conclusion': 'success'}]}
        return {'statuses': [], 'total_count': 0}
    monkeypatch.setattr(checks, 'api_json', successful_ci)
    if trigger == 'operator':
        response = client.post(f"/api/admin/submissions/{original['id']}/refresh-checks", headers=actors.admin.headers)
        assert response.status_code == 200, response.text
    else:
        with factory.begin() as db:
            delivery = WebhookDelivery(id='qa-recover-head-' + uuid.uuid4().hex,
                event_type='reconcile_submission' if trigger == 'queue' else 'check_run',
                payload={'submission_id': original['id'], 'head_sha': original['head_sha']} if trigger == 'queue' else {
                    'repository': {'html_url': original['repository_url']},
                    'check_run': {'head_sha': 'b' * 40, 'pull_requests': [{'number': 1}]},
                })
            db.add(delivery)
            db.flush()
            services.process_delivery(db, delivery)
    assert paths
    with factory() as db:
        row = db.get(Submission, original['id'])
        assert row.head_sha == 'b' * 40 and row.checks_passed
        assert row.status == 'REVIEWING' and services.quorum(db, row)['approved'] == 0
        assert db.get(ReviewLease, interrupted['id']).status == 'STALE'
        assert not db.scalars(select(ImpactCredit).where(ImpactCredit.submission_id == row.id)).all()
