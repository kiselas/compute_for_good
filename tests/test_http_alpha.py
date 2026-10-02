"""Independent HTTP assertions against an isolated real local-alpha project."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import threading
import time
import uuid

import httpx
import pytest
from sqlalchemy import select, text, update


def claim(api, task, user):
    response = api.post(f"/api/tasks/{task['id']}/claim", json={}, headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def submit(api, task, user):
    lease = claim(api, task, user)
    response = api.post(
        f"/api/tasks/{task['id']}/permit",
        json={"lease_token": lease['token']}, headers=user.headers,
    )
    assert response.status_code == 200, response.text
    number = int(uuid.uuid4().hex[:7], 16)
    response = api.post(
        f"/api/tasks/{task['id']}/submissions",
        json={
            "permit_token": response.json()['token'],
            "pr_url": f"{task['_repository_url']}/pull/{number}",
            "head_sha": 'a' * 40, "summary": 'Isolated QA submission',
        }, headers=user.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()


def review(api, submission, user, *, decision='APPROVE', findings=None):
    return api.post(
        f"/api/submissions/{submission['id']}/reviews",
        json={"head_sha": submission['head_sha'], "decision": decision, "summary": f"Private QA verdict by {user.username}",
              "findings": findings or []}, headers=user.headers,
    )


def signed_webhook(api, submission, *, action='synchronize', sha=None, merged=False, delivery=None):
    body = json.dumps({
        "action": action,
        "number": int(submission['pr_url'].rsplit('/', 1)[-1]),
        "repository": {"full_name": submission['pr_url'].split('github.com/', 1)[-1].split('/pull/')[0]},
        "pull_request": {
            "html_url": submission['pr_url'], "head": {"sha": sha or submission['head_sha']},
            "state": 'closed' if merged else 'open', "merged": merged,
            "title": f"[{submission['task_id']}] Isolated QA change",
        },
    }, separators=(',', ':')).encode()
    secret = os.getenv('CFG_TEST_WEBHOOK_SECRET', 'local-demo-webhook-secret').encode()
    signature = 'sha256=' + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return api.post('/api/webhooks/github', content=body, headers={
        'Content-Type': 'application/json', 'X-GitHub-Event': 'pull_request',
        'X-GitHub-Delivery': delivery or f'qa-{uuid.uuid4().hex}',
        'X-Hub-Signature-256': signature,
    })


def test_health_uses_real_database_and_redis(api):
    response = api.get('/api/health')
    assert response.status_code == 200, response.text
    health = response.json()
    assert health['demo_mode'] is True
    assert health['database'] in ('ok', 'connected', True)
    assert health['redis'] in ('ok', 'connected', True)


def test_twenty_concurrent_claims_have_one_winner(api, make_task, actors):
    task = make_task()
    barrier = threading.Barrier(20)

    def contender(_):
        barrier.wait(timeout=10)
        with httpx.Client(base_url=str(api.base_url), timeout=20, trust_env=False) as client:
            return client.post(f"/api/tasks/{task['id']}/claim", json={}, headers=actors.author.headers)

    with ThreadPoolExecutor(max_workers=20) as executor:
        responses = list(executor.map(contender, range(20)))
    codes = [response.status_code for response in responses]
    assert codes.count(200) == 1, [(r.status_code, r.text) for r in responses]
    assert codes.count(409) == 19, [(r.status_code, r.text) for r in responses]
    winner = next(r.json() for r in responses if r.status_code == 200)
    visible = api.get(f"/api/tasks/{task['id']}", headers=actors.author.headers).json()
    assert visible['active_lease']['id'] == winner['id']


def test_lease_ownership_and_token_visibility(api, make_task, actors):
    task = make_task()
    lease = claim(api, task, actors.author)
    for action in ('heartbeat', 'release'):
        response = api.post(f"/api/leases/{lease['id']}/{action}",
                            json={'token': lease['token']}, headers=actors.reviewers[0].headers)
        assert response.status_code in (403, 404), response.text
    response = api.post(f"/api/leases/{lease['id']}/checkpoint",
                        json={'token': lease['token'], 'summary': 'Unauthorized checkpoint'},
                        headers=actors.reviewers[0].headers)
    assert response.status_code in (403, 404), response.text
    for headers in ({}, actors.reviewers[0].headers):
        response = api.get(f"/api/tasks/{task['id']}", headers=headers)
        assert lease['token'] not in response.text
    events = api.get('/api/events')
    assert lease['token'] not in events.text


def test_suspension_committed_after_authentication_blocks_waiting_claim(api, make_task, actors, database):
    task = make_task()
    users = database.table('users')

    def waiting_claim():
        with httpx.Client(base_url=str(api.base_url), timeout=20, trust_env=False) as client:
            return client.post(f"/api/tasks/{task['id']}/claim", json={}, headers=actors.author.headers)

    with database.engine.connect() as holder:
        transaction = holder.begin()
        blocker = holder.scalar(text('SELECT pg_backend_pid()'))
        holder.execute(select(users.c.id).where(users.c.id == actors.author.id).with_for_update())
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(waiting_claim)
            try:
                deadline = time.monotonic() + 8
                observed = False
                while time.monotonic() < deadline:
                    with database.engine.connect() as observer:
                        observed = observer.scalar(text(
                            "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                            "WHERE :blocker = ANY(pg_blocking_pids(pid)) AND wait_event_type = 'Lock')"
                        ), {'blocker': blocker})
                    if observed:
                        break
                    time.sleep(0.05)
                assert observed, 'HTTP claim never reached the held account lock after authentication'
                holder.execute(update(users).where(users.c.id == actors.author.id).values(suspended=True))
                transaction.commit()
            finally:
                if transaction.is_active:
                    transaction.rollback()
            response = future.result(timeout=20)
    assert response.status_code in (401, 403), response.text
    leases = database.table('leases')
    with database.engine.connect() as connection:
        assert connection.execute(select(leases.c.id).where(leases.c.task_id == task['id'])).all() == []


def test_twenty_distinct_claimants_have_one_canonical_lease(api, make_task, actors, database):
    task = make_task()
    contenders = [actors.create('contributor') for _ in range(20)]
    barrier = threading.Barrier(20)

    def contender(user):
        barrier.wait(timeout=10)
        with httpx.Client(base_url=str(api.base_url), timeout=20, trust_env=False) as client:
            return client.post(f"/api/tasks/{task['id']}/claim", json={}, headers=user.headers)

    with ThreadPoolExecutor(max_workers=20) as executor:
        responses = list(executor.map(contender, contenders))
    codes = [response.status_code for response in responses]
    assert codes.count(200) == 1, [(r.status_code, r.text) for r in responses]
    assert codes.count(409) == 19, [(r.status_code, r.text) for r in responses]
    from sqlalchemy import select, func
    leases = database.table('leases')
    with database.engine.connect() as connection:
        active = connection.scalar(select(func.count()).select_from(leases).where(
            leases.c.task_id == task['id'], leases.c.status == 'ACTIVE'))
    assert active == 1


def test_expired_lease_cannot_heartbeat_or_finalize(api, make_task, actors, database):
    task = make_task()
    lease = claim(api, task, actors.author)
    leases = database.table('leases')
    with database.engine.begin() as connection:
        connection.execute(update(leases).where(leases.c.id == lease['id']).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    response = api.post(f"/api/leases/{lease['id']}/heartbeat", json={'token': lease['token']},
                        headers=actors.author.headers)
    assert response.status_code in (403, 409, 410), response.text
    response = api.post(f"/api/tasks/{task['id']}/permit", json={'lease_token': lease['token']},
                        headers=actors.author.headers)
    assert response.status_code in (403, 409, 410), response.text
    replacement = claim(api, task, actors.reviewers[0])
    assert replacement['id'] != lease['id']


def test_expired_permit_cannot_register_submission(api, make_task, actors, database):
    task = make_task()
    lease = claim(api, task, actors.author)
    response = api.post(f"/api/tasks/{task['id']}/permit", json={'lease_token': lease['token']},
                        headers=actors.author.headers)
    assert response.status_code == 200, response.text
    permit = response.json()
    permits = database.table('permits')
    with database.engine.begin() as connection:
        connection.execute(update(permits).where(permits.c.id == permit['id']).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    response = api.post(f"/api/tasks/{task['id']}/submissions", json={
        'permit_token': permit['token'], 'pr_url': f"{task['_repository_url']}/pull/991",
        'head_sha': 'c' * 40, 'summary': 'Must be rejected',
    }, headers=actors.author.headers)
    assert response.status_code in (403, 409, 410), response.text


def test_submission_permit_is_bound_to_its_owner(api, make_task, actors):
    task = make_task()
    lease = claim(api, task, actors.author)
    response = api.post(f"/api/tasks/{task['id']}/permit", json={'lease_token': lease['token']},
                        headers=actors.author.headers)
    assert response.status_code == 200, response.text
    response = api.post(f"/api/tasks/{task['id']}/submissions", json={
        'permit_token': response.json()['token'], 'pr_url': f"{task['_repository_url']}/pull/992",
        'head_sha': 'c' * 40, 'summary': 'A stolen permit must be rejected',
    }, headers=actors.reviewers[0].headers)
    assert response.status_code in (403, 404), response.text


def test_reassigned_task_rejects_old_finalization_attempt(api, make_task, actors, database):
    task = make_task()
    original = claim(api, task, actors.author)
    response = api.post(f"/api/tasks/{task['id']}/permit", json={'lease_token': original['token']},
                        headers=actors.author.headers)
    assert response.status_code == 200, response.text
    old_permit = response.json()
    leases = database.table('leases')
    with database.engine.begin() as connection:
        connection.execute(update(leases).where(leases.c.id == original['id']).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    replacement = claim(api, task, actors.reviewers[0])
    stale = api.post(f"/api/tasks/{task['id']}/submissions", json={
        'permit_token': old_permit['token'], 'pr_url': f"{task['_repository_url']}/pull/993",
        'head_sha': 'a' * 40, 'summary': 'Old finalization must not win',
    }, headers=actors.author.headers)
    assert stale.status_code == 409, stale.text
    response = api.post(f"/api/tasks/{task['id']}/permit", json={'lease_token': replacement['token']},
                        headers=actors.reviewers[0].headers)
    assert response.status_code == 200, response.text
    valid = api.post(f"/api/tasks/{task['id']}/submissions", json={
        'permit_token': response.json()['token'], 'pr_url': f"{task['_repository_url']}/pull/994",
        'head_sha': 'b' * 40, 'summary': 'Replacement is the canonical attempt',
    }, headers=actors.reviewers[0].headers)
    assert valid.status_code == 200, valid.text
    assert valid.json()['author_id'] == actors.reviewers[0].id


def test_consumed_permit_cannot_create_another_submission(api, make_task, actors, database):
    task = make_task()
    lease = claim(api, task, actors.author)
    prepared = api.post(f"/api/tasks/{task['id']}/permit", json={'lease_token': lease['token']},
                        headers=actors.author.headers)
    assert prepared.status_code == 200, prepared.text
    body = {'permit_token': prepared.json()['token'],
            'pr_url': f"{task['_repository_url']}/pull/995", 'head_sha': 'a' * 40,
            'summary': 'Exactly one canonical registration'}
    endpoint = f"/api/tasks/{task['id']}/submissions"
    first = api.post(endpoint, json=body, headers=actors.author.headers)
    assert first.status_code == 200, first.text
    for pr_number in (995, 996):
        body['pr_url'] = f"{task['_repository_url']}/pull/{pr_number}"
        repeated = api.post(endpoint, json=body, headers=actors.author.headers)
        assert repeated.status_code == 409, repeated.text
    from sqlalchemy import select, func
    submissions = database.table('submissions')
    with database.engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(submissions).where(
            submissions.c.task_id == task['id']))
    assert count == 1


def test_author_cannot_review_own_submission(api, make_task, actors):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    response = review(api, submission, actors.author)
    assert response.status_code == 403, response.text


def test_blind_review_is_hidden_until_reviewer_submits(api, make_task, actors):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    first = review(api, submission, actors.reviewers[0], decision='BLOCK',
                   findings=[{'severity': 'HIGH', 'description': 'Private QA finding'}])
    assert first.status_code == 200, first.text
    secret_summary = first.json()['summary']
    before = api.get(f"/api/submissions/{submission['id']}", headers=actors.reviewers[1].headers)
    assert before.status_code == 200, before.text
    assert secret_summary not in before.text
    assert before.json()['status'] == 'REVIEWING'
    assert before.json()['quorum'].get('blind') is True
    for key, masked in (('approved', 0), ('blocked', False), ('passed', False)):
        assert before.json()['quorum'].get(key) == masked
    public = api.get(f"/api/submissions/{submission['id']}")
    assert secret_summary not in public.text
    for path in ('/api/submissions', '/api/review-work', '/api/events'):
        response = api.get(path, headers=actors.reviewers[1].headers)
        assert secret_summary not in response.text
    response = review(api, submission, actors.reviewers[1])
    assert response.status_code == 200, response.text
    after = api.get(f"/api/submissions/{submission['id']}", headers=actors.reviewers[1].headers)
    assert secret_summary in after.text


def test_normal_requires_two_distinct_reviews(api, make_task, actors):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    response = review(api, submission, actors.reviewers[0])
    assert response.status_code == 200, response.text
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['quorum']['required'] == 2
    assert state['quorum']['approved'] == 1
    assert state['quorum']['passed'] is False
    duplicate = review(api, submission, actors.reviewers[0])
    assert duplicate.status_code == 409, duplicate.text
    response = review(api, submission, actors.reviewers[1])
    assert response.status_code == 200, response.text
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['quorum']['approved'] == 2
    assert state['quorum']['passed'] is True


def test_critical_requires_five_frontier_reviews_and_human(api, make_task, actors):
    submission = submit(api, make_task(risk='CRITICAL', required_model_tier='FRONTIER'), actors.author)
    denied = review(api, submission, actors.basic)
    assert denied.status_code == 403, denied.text
    for index, reviewer in enumerate(actors.reviewers):
        response = review(api, submission, reviewer)
        assert response.status_code == 200, response.text
        state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
        assert state['quorum']['required'] == 5
        assert state['quorum']['human_required'] is True
        assert state['quorum']['passed'] is (index == 4)


def test_critical_high_finding_blocks_despite_other_approvals(api, make_task, actors):
    submission = submit(api, make_task(risk='CRITICAL', required_model_tier='FRONTIER'), actors.author)
    response = review(api, submission, actors.reviewers[0], decision='BLOCK',
                      findings=[{'severity': 'HIGH', 'description': 'QA privilege bypass evidence'}])
    assert response.status_code == 200, response.text
    for reviewer in actors.reviewers[1:]:
        response = review(api, submission, reviewer)
        assert response.status_code == 200, response.text
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['quorum']['required'] == 5
    assert state['quorum']['blocked'] is True
    assert state['quorum']['passed'] is False


def test_low_tier_cannot_claim_critical_task(api, make_task, actors):
    task = make_task(risk='CRITICAL', required_model_tier='FRONTIER')
    response = api.post(f"/api/tasks/{task['id']}/claim", json={}, headers=actors.basic.headers)
    assert response.status_code == 403, response.text


def test_webhook_requires_signature_and_deduplicates(api, make_task, actors):
    submission = submit(api, make_task(), actors.author)
    invalid = api.post('/api/webhooks/github', json={'action': 'synchronize'}, headers={
        'X-Hub-Signature-256': 'sha256=' + '0' * 64, 'X-GitHub-Delivery': f'qa-{uuid.uuid4().hex}',
    })
    assert invalid.status_code in (401, 403), invalid.text
    delivery = f'qa-{uuid.uuid4().hex}'
    first = signed_webhook(api, submission, delivery=delivery)
    assert first.status_code == 200, first.text
    assert first.json()['duplicate'] is False
    second = signed_webhook(api, submission, delivery=delivery)
    assert second.status_code == 200, second.text
    assert second.json()['duplicate'] is True


def test_changed_head_sha_invalidates_old_reviews(api, make_task, actors):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    for reviewer in actors.reviewers[:2]:
        response = review(api, submission, reviewer)
        assert response.status_code == 200, response.text
    response = signed_webhook(api, submission, sha='b' * 40)
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 10
    while True:
        state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
        if state['head_sha'] == 'b' * 40 or time.monotonic() >= deadline:
            break
        time.sleep(0.2)
    assert state['head_sha'] == 'b' * 40
    assert state['quorum']['approved'] == 0
    assert state['quorum']['passed'] is False
    assert all(review['is_current'] is False for review in state.get('reviews', []))


def test_review_of_previous_head_cannot_be_attributed_to_new_head(api, make_task, actors):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    response = signed_webhook(api, submission, sha='d' * 40)
    assert response.status_code == 200, response.text
    deadline = time.monotonic() + 10
    while True:
        current = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
        if current['head_sha'] == 'd' * 40 or time.monotonic() >= deadline:
            break
        time.sleep(0.2)
    assert current['head_sha'] == 'd' * 40
    stale = review(api, submission, actors.reviewers[0])
    assert stale.status_code == 409, stale.text
    accepted = review(api, current, actors.reviewers[0])
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['head_sha'] == 'd' * 40


def test_operator_only_moderation_and_task_creation(api, make_task, actors, qa_project):
    response = api.patch(f"/api/projects/{qa_project['id']}", json={'status': 'REJECTED'},
                         headers=actors.author.headers)
    assert response.status_code == 403, response.text
    response = api.post('/api/tasks', json={
        'project_id': qa_project['id'], 'title': 'Forbidden QA creation',
        'description': 'Should never be created', 'difficulty': 'EASY', 'risk': 'LOW',
        'required_model_tier': 'BASIC', 'estimated_minutes': 15,
        'acceptance_criteria': ['Must not exist'], 'allowed_paths': ['docs/**'],
        'forbidden_paths': [], 'verification_commands': ['pytest'],
    }, headers=actors.author.headers)
    assert response.status_code == 403, response.text
    task = make_task()
    submission = submit(api, task, actors.author)
    response = api.post(f"/api/demo/submissions/{submission['id']}/merge", json={},
                        headers=actors.author.headers)
    assert response.status_code == 403, response.text


def test_demo_merge_is_explicit_and_credit_is_idempotent(api, make_task, actors, database):
    submission = submit(api, make_task(), actors.author)
    response = review(api, submission, actors.reviewers[0])
    assert response.status_code == 200, response.text
    endpoint = f"/api/demo/submissions/{submission['id']}/merge"
    first = api.post(endpoint, json={}, headers=actors.admin.headers)
    assert first.status_code == 200, first.text
    assert first.json()['is_demo'] is True
    second = api.post(endpoint, json={}, headers=actors.admin.headers)
    assert second.status_code == 200, second.text
    events = database.table('impact_credits')
    from sqlalchemy import select, func
    with database.engine.connect() as connection:
        count = connection.scalar(select(func.count()).select_from(events).where(
            events.c.submission_id == submission['id']))
    assert count == 1
