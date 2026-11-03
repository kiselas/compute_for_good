"""Owner acceptance is a separate, exact-head alternative to independent review."""
import uuid

import pytest
from sqlalchemy import insert, update

from test_http_alpha import submit
from test_maintainer_planning import browser_actor
from test_review_workflow import reserve, leased_review


@pytest.fixture
def owned(api, database, actors, qa_project, make_task):
    project = {**qa_project, 'id': str(uuid.uuid4()), 'slug': 'owner-' + uuid.uuid4().hex,
               'repository_url': 'https://github.com/cfg-alpha-test/' + uuid.uuid4().hex,
               'maintainer_id': actors.author.id}
    with database.engine.begin() as connection:
        connection.execute(insert(database.table('projects')).values(**project))
    submission = submit(api, make_task(project_id=project['id'], risk='NORMAL'), actors.author)
    owner = browser_actor(database, actors, actors.author)
    return project, submission, owner


def decide(api, submission, owner, approved=True, **overrides):
    return api.post(f"/api/submissions/{submission['id']}/maintainer-approval", headers=owner.headers,
                    json={'head_sha': submission['head_sha'], 'approved': approved,
                          'reason': 'Owner verified this exact commit against the task', **overrides})


def test_project_owner_can_accept_own_submission_without_fabricating_reviews(api, owned, actors):
    _, submission, owner = owned
    result = decide(api, submission, owner)
    assert result.status_code == 200, result.text
    state = result.json()
    assert state['quorum']['approved'] == 0
    assert state['quorum']['required'] == 2
    assert state['quorum']['maintainer_approved'] is True
    assert state['quorum']['passed'] is True
    assert state['status'] == 'AWAITING_MAINTAINER'
    assert state['reviews'] == []
    hidden = api.get(f"/api/submissions/{submission['id']}").json()
    assert hidden['quorum']['blind'] is True
    assert hidden['quorum']['maintainer_approved'] is False
    assert not hidden['can_approve_as_maintainer']
    assert api.post(f"/api/submissions/{submission['id']}/review-claim",
                    json={'head_sha': submission['head_sha']}, headers=actors.reviewers[0].headers).status_code == 409


def test_owner_acceptance_keeps_findings_and_can_be_withdrawn(api, owned, actors):
    _, submission, owner = owned
    reviewer = actors.reviewers[0]
    lease = reserve(api, submission, reviewer)
    review = leased_review(api, submission, reviewer, lease, decision='REQUEST_CHANGES',
                           findings=[{'severity': 'HIGH', 'description': 'Reproduced final-state mismatch'}])
    assert review.status_code == 200, review.text
    accepted = decide(api, submission, owner).json()
    assert accepted['quorum']['review_blocked'] is True
    assert accepted['quorum']['blocked'] is False
    assert accepted['quorum']['passed'] is True
    assert accepted['reviews'][0]['decision'] == 'REQUEST_CHANGES'
    revoked = decide(api, submission, owner, approved=False).json()
    assert revoked['quorum']['maintainer_approved'] is False
    assert revoked['quorum']['blocked'] is True
    assert revoked['status'] == 'CHANGES_NEEDED'


def test_owner_acceptance_does_not_bypass_ci(api, database, owned, actors):
    _, submission, owner = owned
    with database.engine.begin() as connection:
        rows = database.table('submissions')
        connection.execute(update(rows).where(rows.c.id == submission['id']).values(checks_passed=False))
    accepted = decide(api, submission, owner).json()
    assert accepted['quorum']['passed'] is True
    assert accepted['status'] == 'REVIEWING'
    assert not accepted['checks_passed']
    merged = api.post(f"/api/demo/submissions/{submission['id']}/merge", json={}, headers=actors.admin.headers)
    assert merged.status_code == 409


def test_only_current_browser_owner_may_decide(api, database, owned, actors):
    project, submission, owner = owned
    outsider = browser_actor(database, actors, actors.create('contributor'))
    assert decide(api, submission, outsider).status_code == 403
    assert decide(api, submission, actors.admin).status_code == 403
    assert decide(api, submission, actors.author).status_code == 403  # scoped PAT, same owner
    assert decide(api, submission, owner, head_sha='b' * 40).status_code == 409
    assert decide(api, submission, owner, reason=' ' * 15).status_code == 422
    assert decide(api, submission, owner).status_code == 200
    with database.engine.begin() as connection:
        projects = database.table('projects')
        connection.execute(update(projects).where(projects.c.id == project['id']).values(maintainer_id=outsider.id))
    state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
    assert state['quorum']['maintainer_approved'] is False
    assert state['quorum']['passed'] is False
    assert decide(api, submission, owner).status_code == 403


def test_two_independent_reviews_still_pass_without_owner_acceptance(api, owned, actors):
    _, submission, owner = owned
    for reviewer in actors.reviewers[:2]:
        lease = reserve(api, submission, reviewer)
        response = leased_review(api, submission, reviewer, lease)
        assert response.status_code == 200, response.text
    state = api.get(f"/api/submissions/{submission['id']}", headers=owner.headers).json()
    assert state['quorum']['approved'] == 2
    assert not state['quorum']['maintainer_approved']
    assert state['quorum']['passed'] is True
    assert state['status'] == 'AWAITING_MAINTAINER'


def test_active_reviewer_can_release_after_owner_acceptance(api, owned, actors):
    _, submission, owner = owned
    reviewer = actors.reviewers[0]
    lease = reserve(api, submission, reviewer)
    assert decide(api, submission, owner).status_code == 200
    assert leased_review(api, submission, reviewer, lease).status_code == 409
    released = api.post(f"/api/review-leases/{lease['id']}/release",
                        json={'token': lease['token']}, headers=reviewer.headers)
    assert released.status_code == 200, released.text


def test_new_head_and_return_to_old_sha_require_fresh_owner_acceptance(api, database, owned, actors):
    from sqlalchemy.orm import Session
    from computeforgood import services
    from computeforgood.models import Submission

    _, submission, owner = owned
    assert decide(api, submission, owner).status_code == 200

    def observe(sha):
        with Session(database.engine) as db:
            row = db.get(Submission, submission['id'])
            services.observe_pr_state(db, row, {'head': {'sha': sha}}, closed=False)
            db.commit()
        return api.get(f"/api/submissions/{submission['id']}", headers=owner.headers).json()

    current = observe('b' * 40)
    assert not current['quorum']['maintainer_approved']
    assert not current['quorum']['passed']
    assert decide(api, submission, owner).status_code == 409
    assert decide(api, current, owner).status_code == 200
    reverted = observe(submission['head_sha'])
    assert not reverted['quorum']['maintainer_approved']
    assert not reverted['quorum']['passed']
