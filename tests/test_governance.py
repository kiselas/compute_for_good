import uuid
from sqlalchemy import insert, select

REASON = 'Independent QA verified a reservation recovery case'


def test_operator_release_revokes_permit_and_keeps_private_audit(api, actors, make_task):
    task = make_task()
    lease = api.post(f"/api/tasks/{task['id']}/claim", json={}, headers=actors.author.headers).json()
    permit = api.post(f"/api/tasks/{task['id']}/permit", json={'lease_token': lease['token']}, headers=actors.author.headers)
    assert permit.status_code == 200, permit.text
    path = f"/api/admin/leases/{lease['id']}/force-release"
    assert api.post(path, json={'reason': REASON}, headers=actors.author.headers).status_code == 403
    response = api.post(path, json={'reason': REASON}, headers=actors.admin.headers)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'REVOKED'
    assert api.get(f"/api/tasks/{task['id']}").json()['status'] == 'AVAILABLE'
    assert api.post(f"/api/leases/{lease['id']}/heartbeat", json={'token': lease['token']}, headers=actors.author.headers).status_code == 409
    records = api.get('/api/admin/actions', headers=actors.admin.headers).json()
    assert any(r['target_id'] == lease['id'] and r['reason'] == REASON for r in records)
    assert api.get('/api/admin/actions', headers=actors.author.headers).status_code == 403
    assert REASON not in api.get('/api/events').text


def test_operator_task_edit_safety_and_invalidation(api, actors, make_task, database):
    task = make_task()
    path = f"/api/admin/tasks/{task['id']}"
    assert api.patch(path, headers=actors.admin.headers, json={'reason': REASON, 'risk': 'HIGH', 'required_model_tier': 'STRONG'}).status_code == 422
    response = api.patch(path, headers=actors.admin.headers, json={'reason': REASON, 'risk': 'NORMAL', 'required_model_tier': 'STRONG', 'title': 'Reviewed contract amendment'})
    assert response.status_code == 200, response.text
    tasks = database.table('tasks')
    with database.engine.connect() as db:
        assert db.scalar(select(tasks.c.version).where(tasks.c.id == task['id'])) == 2
    lease = api.post(f"/api/tasks/{task['id']}/claim", headers=actors.author.headers, json={})
    assert lease.status_code == 200
    assert api.patch(path, headers=actors.admin.headers, json={'reason': REASON, 'title': 'Unsafe mid-lease edit'}).status_code == 409
    response = api.post(path + '/invalidate', headers=actors.admin.headers, json={'reason': REASON})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'INVALID'
    assert api.post(f"/api/tasks/{task['id']}/claim", headers=actors.reviewers[0].headers, json={}).status_code == 409


def test_participant_suspension_ends_reservations(api, actors, make_task):
    task = make_task()
    assert api.post(f"/api/tasks/{task['id']}/claim", headers=actors.author.headers, json={}).status_code == 200
    path = f"/api/admin/users/{actors.author.id}/suspend"
    response = api.post(path, headers=actors.admin.headers, json={'reason': REASON, 'suspended': True})
    assert response.status_code == 200, response.text
    assert api.get('/api/me', headers=actors.author.headers).status_code == 401
    assert api.get(f"/api/tasks/{task['id']}").json()['status'] == 'AVAILABLE'
    assert api.post(f"/api/admin/users/{actors.admin.id}/suspend", headers=actors.admin.headers, json={'reason': REASON}).status_code == 409
    assert api.post(path, headers=actors.admin.headers, json={'reason': REASON, 'suspended': False}).status_code == 200
    assert api.get('/api/me', headers=actors.author.headers).status_code == 200


def test_project_pause_requires_reverification(api, database, actors, qa_project, make_task):
    private_project = dict(qa_project, id=str(uuid.uuid4()), slug=qa_project['slug'] + '-pause-' + uuid.uuid4().hex[:5], repository_url='https://github.com/cfg-alpha-test/' + uuid.uuid4().hex)
    with database.engine.begin() as db:
        db.execute(insert(database.table('projects')).values(**private_project))
    task = make_task(project_id=private_project['id'])
    assert api.post(f"/api/tasks/{task['id']}/claim", headers=actors.author.headers, json={}).status_code == 200
    path = f"/api/admin/projects/{private_project['id']}/suspend"
    assert api.post(path, headers=actors.admin.headers, json={'reason': REASON, 'suspended': True}).status_code == 200
    assert api.post(f"/api/tasks/{task['id']}/claim", headers=actors.reviewers[0].headers, json={}).status_code == 403
    response = api.post(path, headers=actors.admin.headers, json={'reason': REASON, 'suspended': False})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'CANDIDATE'
    assert api.post(f"/api/tasks/{task['id']}/claim", headers=actors.reviewers[0].headers, json={}).status_code == 403
