from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import threading
import uuid

import httpx
from sqlalchemy import insert, select, update

from test_http_alpha import review, submit


def reserve(api, submission, user):
    response = api.post(f"/api/submissions/{submission['id']}/review-claim",
                        json={'head_sha': submission['head_sha']}, headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def leased_review(api, submission, user, lease, *, decision='APPROVE', findings=None):
    return api.post(f"/api/submissions/{submission['id']}/reviews", headers=user.headers, json={
        'head_sha': submission['head_sha'], 'decision': decision, 'summary': 'Independent leased QA review',
        'findings': findings or [], 'review_lease_id': lease['id'], 'review_lease_token': lease['token'],
    })


def revise(api, submission, user, sha='e' * 40):
    response = api.post(f"/api/submissions/{submission['id']}/resubmit",
                        json={'head_sha': sha, 'summary': 'Revision of the same canonical PR'}, headers=user.headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_twenty_review_claimants_reserve_one_low_risk_slot(api, make_task, actors, database):
    submission = submit(api, make_task(), actors.author)
    users = [actors.create('reviewer') for _ in range(20)]
    barrier = threading.Barrier(20)

    def contender(user):
        barrier.wait(timeout=10)
        with httpx.Client(base_url=str(api.base_url), timeout=20, trust_env=False) as client:
            return client.post(f"/api/submissions/{submission['id']}/review-claim",
                               json={'head_sha': submission['head_sha']}, headers=user.headers)

    with ThreadPoolExecutor(max_workers=20) as executor:
        responses = list(executor.map(contender, users))
    assert sum(response.status_code == 200 for response in responses) == 1
    assert sum(response.status_code == 409 for response in responses) == 19, [response.text for response in responses]
    winner = next(response.json() for response in responses if response.status_code == 200)
    leases = database.table('review_leases')
    with database.engine.connect() as connection:
        rows = connection.execute(select(leases.c.id).where(
            leases.c.submission_id == submission['id'], leases.c.status == 'ACTIVE')).all()
    assert rows == [(winner['id'],)]


def test_review_lease_slots_ownership_heartbeat_and_release(api, make_task, actors):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    for forbidden in (actors.author, actors.basic):
        response = api.post(f"/api/submissions/{submission['id']}/review-claim",
                            json={'head_sha': submission['head_sha']}, headers=forbidden.headers)
        assert response.status_code == 403, response.text
    first = reserve(api, submission, actors.reviewers[0])
    duplicate = api.post(f"/api/submissions/{submission['id']}/review-claim",
                         json={'head_sha': submission['head_sha']}, headers=actors.reviewers[0].headers)
    assert duplicate.status_code == 409, duplicate.text
    second = reserve(api, submission, actors.reviewers[1])
    assert first['work_item_id'] != second['work_item_id']
    full = api.post(f"/api/submissions/{submission['id']}/review-claim",
                    json={'head_sha': submission['head_sha']}, headers=actors.reviewers[2].headers)
    assert full.status_code == 409, full.text
    for action in ('heartbeat', 'release'):
        stolen = api.post(f"/api/review-leases/{first['id']}/{action}",
                          json={'token': first['token']}, headers=actors.reviewers[1].headers)
        assert stolen.status_code == 403, stolen.text
    heartbeat = api.post(f"/api/review-leases/{first['id']}/heartbeat",
                         json={'token': first['token']}, headers=actors.reviewers[0].headers)
    assert heartbeat.status_code == 200, heartbeat.text
    released = api.post(f"/api/review-leases/{first['id']}/release",
                        json={'token': first['token']}, headers=actors.reviewers[0].headers)
    assert released.status_code == 200, released.text
    replacement = reserve(api, submission, actors.reviewers[2])
    assert replacement['work_item_id'] == first['work_item_id']
    assert replacement['id'] != first['id']
    own = api.get('/api/review-leases', headers=actors.reviewers[0].headers)
    assert first['token'] not in own.text
    others = api.get('/api/review-leases', headers=actors.reviewers[1].headers)
    assert first['id'] not in others.text


def test_expired_review_cannot_submit_and_slot_is_recoverable(api, make_task, actors, database):
    submission = submit(api, make_task(), actors.author)
    old = reserve(api, submission, actors.reviewers[0])
    leases = database.table('review_leases')
    with database.engine.begin() as connection:
        connection.execute(update(leases).where(leases.c.id == old['id']).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
    stale = leased_review(api, submission, actors.reviewers[0], old)
    assert stale.status_code == 409, stale.text
    replacement = reserve(api, submission, actors.reviewers[1])
    assert replacement['work_item_id'] == old['work_item_id']
    accepted = leased_review(api, submission, actors.reviewers[1], replacement)
    assert accepted.status_code == 200, accepted.text
    replay = leased_review(api, submission, actors.reviewers[1], replacement)
    assert replay.status_code == 409, replay.text
    with database.engine.connect() as connection:
        status = connection.scalar(select(leases.c.status).where(leases.c.id == replacement['id']))
    assert status == 'COMPLETED'


def test_head_revision_invalidates_reserved_review_without_new_canonical_pr(api, make_task, actors, database):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    old = reserve(api, submission, actors.reviewers[0])
    current = revise(api, submission, actors.author)
    assert current['id'] == submission['id']
    assert current['pr_url'] == submission['pr_url']
    heartbeat = api.post(f"/api/review-leases/{old['id']}/heartbeat",
                         json={'token': old['token']}, headers=actors.reviewers[0].headers)
    assert heartbeat.status_code == 409, heartbeat.text
    stale = leased_review(api, submission, actors.reviewers[0], old)
    assert stale.status_code == 409, stale.text
    fresh = reserve(api, current, actors.reviewers[0])
    assert fresh['head_sha'] == current['head_sha']
    assert fresh['work_item_id'] != old['work_item_id']
    task = api.get(f"/api/tasks/{submission['task_id']}", headers=actors.author.headers).json()
    assert task['status'] != 'AVAILABLE'
    submissions = database.table('submissions')
    with database.engine.connect() as connection:
        rows = connection.execute(select(submissions.c.id).where(
            submissions.c.task_id == submission['task_id'])).all()
    assert rows == [(submission['id'],)]


def test_unresolved_security_finding_survives_new_sha_and_requires_independent_evidence(api, make_task, actors):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    lease = reserve(api, submission, actors.reviewers[0])
    blocked = leased_review(api, submission, actors.reviewers[0], lease, decision='BLOCK', findings=[{
        'severity': 'HIGH', 'description': 'Security regression must be verified independently',
    }])
    assert blocked.status_code == 200, blocked.text
    original_review = blocked.json()
    current = revise(api, submission, actors.author)
    for reviewer in actors.reviewers[:2]:
        lease = reserve(api, current, reviewer)
        accepted = leased_review(api, current, reviewer, lease)
        assert accepted.status_code == 200, accepted.text
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['quorum']['approved'] == 2
    assert state['quorum']['blocked'] is True
    assert state['quorum']['passed'] is False
    endpoint = f"/api/reviews/{original_review['id']}/findings/0/resolve"
    evidence = {'head_sha': current['head_sha'], 'evidence': 'Verified the corrected authorization test on current SHA'}
    for outsider in (actors.author, actors.reviewers[2]):
        denied = api.post(endpoint, json=evidence, headers=outsider.headers)
        assert denied.status_code == 403, denied.text
    resolved = api.post(endpoint, json=evidence, headers=actors.reviewers[0].headers)
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()['head_sha'] == current['head_sha']
    assert resolved.json()['resolver_role'] == 'ORIGINAL_REVIEWER'
    repeated = api.post(endpoint, json=evidence, headers=actors.reviewers[0].headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()['id'] == resolved.json()['id']
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['quorum']['blocked'] is False
    assert state['quorum']['passed'] is True
    assert next(row for row in state['reviews'] if row['id'] == original_review['id'])['findings'][0]['severity'] == 'HIGH'
    private = api.get(f"/api/reviews/{original_review['id']}/finding-resolutions", headers=actors.reviewers[2].headers)
    assert private.status_code == 403, private.text
    own = api.get(f"/api/reviews/{original_review['id']}/finding-resolutions", headers=actors.author.headers)
    assert own.status_code == 200, own.text
    assert len(own.json()) == 1


def test_non_demo_submission_requires_review_lease_even_when_demo_mode_is_enabled(api, make_task, actors, database):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    submissions = database.table('submissions')
    with database.engine.begin() as connection:
        connection.execute(update(submissions).where(submissions.c.id == submission['id']).values(is_demo=False))
    missing = review(api, submission, actors.reviewers[0])
    assert missing.status_code == 403, missing.text
    lease = reserve(api, submission, actors.reviewers[0])
    accepted = leased_review(api, submission, actors.reviewers[0], lease)
    assert accepted.status_code == 200, accepted.text


def test_resubmission_is_author_only_and_terminal_state_cannot_reopen(api, make_task, actors):
    submission = submit(api, make_task(), actors.author)
    endpoint = f"/api/submissions/{submission['id']}/resubmit"
    forbidden = api.post(endpoint, json={'head_sha': 'f' * 40}, headers=actors.reviewers[0].headers)
    assert forbidden.status_code == 403, forbidden.text
    unchanged = api.post(endpoint, json={'head_sha': submission['head_sha']}, headers=actors.author.headers)
    assert unchanged.status_code == 409, unchanged.text
    lease = reserve(api, submission, actors.reviewers[0])
    result = leased_review(api, submission, actors.reviewers[0], lease)
    assert result.status_code == 200, result.text
    merged = api.post(f"/api/demo/submissions/{submission['id']}/merge", json={}, headers=actors.admin.headers)
    assert merged.status_code == 200, merged.text
    reopened = api.post(endpoint, json={'head_sha': 'f' * 40}, headers=actors.author.headers)
    assert reopened.status_code == 409, reopened.text


def test_scoped_operator_agent_cannot_adjudicate_other_reviewers_findings(api, make_task, actors):
    submission = submit(api, make_task(risk='NORMAL'), actors.author)
    lease = reserve(api, submission, actors.reviewers[0])
    result = leased_review(api, submission, actors.reviewers[0], lease, decision='BLOCK', findings=[{
        'severity': 'HIGH', 'description': 'Independent finding with operator authority boundary',
    }])
    assert result.status_code == 200, result.text
    scoped_operator = actors.scoped_credential(actors.create('operator'))
    endpoint = f"/api/reviews/{result.json()['id']}/findings/0/resolve"
    body = {'head_sha': submission['head_sha'], 'evidence': 'Evidence does not authorize this operator agent token'}
    denied = api.post(endpoint, json=body, headers=scoped_operator.headers)
    assert denied.status_code == 403, denied.text
    original_reviewer = actors.scoped_credential(actors.reviewers[0])
    accepted = api.post(endpoint, json=body, headers=original_reviewer.headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()['resolver_role'] == 'ORIGINAL_REVIEWER'


def test_project_reverification_reopens_only_unfinished_current_review_slots(api, make_task, actors, database, qa_project):
    private = {**qa_project, 'id': str(uuid.uuid4()), 'slug': f"qa-resume-{uuid.uuid4().hex[:12]}",
               'name': 'Isolated QA project suspension and resume',
               'repository_url': f"https://github.com/cfg-alpha-test/qa-resume-{uuid.uuid4().hex[:12]}"}
    with database.engine.begin() as connection:
        connection.execute(insert(database.table('projects')).values(**private))
    submission = submit(api, make_task(project_id=private['id'], risk='NORMAL'), actors.author)
    completed_lease = reserve(api, submission, actors.reviewers[0])
    completed = leased_review(api, submission, actors.reviewers[0], completed_lease)
    assert completed.status_code == 200, completed.text
    interrupted = reserve(api, submission, actors.reviewers[1])
    endpoint = f"/api/admin/projects/{private['id']}/suspend"
    paused = api.post(endpoint, json={'suspended': True, 'reason': 'Verify safe interruption of independent reviews'},
                      headers=actors.admin.headers)
    assert paused.status_code == 200, paused.text
    reopened = api.post(endpoint, json={'suspended': False, 'reason': 'Restore intake for explicit re-verification'},
                        headers=actors.admin.headers)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()['status'] == 'CANDIDATE'
    candidate = api.post(f"/api/submissions/{submission['id']}/review-claim",
                         json={'head_sha': submission['head_sha']}, headers=actors.reviewers[1].headers)
    assert candidate.status_code == 403, candidate.text
    verified = api.patch(f"/api/projects/{private['id']}", json={'status': 'VERIFIED'}, headers=actors.admin.headers)
    assert verified.status_code == 200, verified.text
    resumed = reserve(api, submission, actors.reviewers[1])
    assert resumed['work_item_id'] == interrupted['work_item_id']
    assert resumed['id'] != interrupted['id']
    assert resumed['work_item_id'] != completed_lease['work_item_id']
    stale = leased_review(api, submission, actors.reviewers[1], interrupted)
    assert stale.status_code == 409, stale.text
    result = leased_review(api, submission, actors.reviewers[1], resumed)
    assert result.status_code == 200, result.text
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['quorum']['approved'] == 2
    assert state['quorum']['passed'] is True


def test_resolution_on_fixed_sha_does_not_approve_return_to_known_bad_sha(api, make_task, actors):
    original = submit(api, make_task(risk='NORMAL'), actors.author)
    for index, reviewer in enumerate(actors.reviewers[:2]):
        lease = reserve(api, original, reviewer)
        result = leased_review(api, original, reviewer, lease, findings=[{
            'severity': 'HIGH', 'description': 'Known bad commit must not regain an old approval',
        }] if index == 0 else [])
        assert result.status_code == 200, result.text
        if index == 0:
            finding_review = result.json()
    corrected = revise(api, original, actors.author, sha='b' * 40)
    for reviewer in actors.reviewers[:2]:
        lease = reserve(api, corrected, reviewer)
        result = leased_review(api, corrected, reviewer, lease)
        assert result.status_code == 200, result.text
    resolved = api.post(f"/api/reviews/{finding_review['id']}/findings/0/resolve", json={
        'head_sha': corrected['head_sha'], 'evidence': 'Verified the regression is fixed at this exact corrected commit',
    }, headers=actors.reviewers[0].headers)
    assert resolved.status_code == 200, resolved.text
    assert api.get(f"/api/submissions/{original['id']}", headers=actors.admin.headers).json()['quorum']['passed'] is True
    reverted = revise(api, corrected, actors.author, sha=original['head_sha'])
    assert reverted['quorum']['approved'] == 2
    assert reverted['quorum']['blocked'] is True
    assert reverted['quorum']['passed'] is False
    merged = api.post(f"/api/demo/submissions/{original['id']}/merge", json={}, headers=actors.admin.headers)
    assert merged.status_code == 409, merged.text
