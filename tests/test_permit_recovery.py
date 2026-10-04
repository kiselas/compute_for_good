"""HTTP/PostgreSQL permit rotation after recovering an owned browser lease."""
import importlib
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from computeforgood.models import Permit
from test_backend_boundaries import source_client
from test_http_alpha import claim


def test_reload_rotates_permit_without_reopening_or_foreign_access(source_client, make_task, actors):
    client, factory = source_client
    task = make_task()
    lease = claim(client, task, actors.author)
    endpoint = f"/api/tasks/{task['id']}/permit"
    body = {'lease_token': lease['token']}
    prepared = client.post(endpoint, headers=actors.author.headers, json=body)
    assert prepared.status_code == 200, prepared.text
    old = prepared.json()
    # A different participant or wrong/recovered-from-another-task lease cannot
    # rotate the legitimate owner's permit, even with a valid author identity.
    assert client.post(endpoint, headers=actors.reviewers[0].headers, json=body).status_code == 403
    assert client.post(endpoint, headers=actors.author.headers, json={'lease_token': 'wrong-lease-token'}).status_code == 403
    other_task = make_task()
    other = claim(client, other_task, actors.reviewers[0])
    assert client.post(endpoint, headers=actors.author.headers, json={'lease_token': other['token']}).status_code == 403
    with factory() as db:
        assert db.get(Permit, old['id']).status == 'ACTIVE'
    # A fresh client has no permit state. It only possesses the recovered lease.
    with TestClient(importlib.import_module('computeforgood.app').api) as reloaded:
        response = reloaded.post(endpoint, headers=actors.author.headers, json=body)
        assert response.status_code == 200, response.text
        replacement = response.json()
        assert replacement['id'] != old['id'] and replacement['token'] != old['token']
        assert replacement['expires_at'] <= lease['expires_at']
        with factory() as db:
            permits = db.scalars(select(Permit).where(Permit.task_id == task['id'])).all()
            assert len([row for row in permits if row.status == 'ACTIVE']) == 1
            assert db.get(Permit, old['id']).status == 'REVOKED'
        submission_body = {'permit_token': old['token'],
            'pr_url': task['_repository_url'] + '/pull/' + str(int(uuid.uuid4().hex[:8], 16)),
            'head_sha': 'a' * 40, 'summary': 'Recovered browser lease finalization'}
        assert reloaded.post(f"/api/tasks/{task['id']}/submissions", headers=actors.author.headers,
                             json=submission_body).status_code == 409
        submission_body['permit_token'] = replacement['token']
        registered = reloaded.post(f"/api/tasks/{task['id']}/submissions", headers=actors.author.headers,
                                   json=submission_body)
        assert registered.status_code == 200, registered.text
        assert reloaded.post(endpoint, headers=actors.author.headers, json=body).status_code == 409
    with factory() as db:
        assert db.get(Permit, replacement['id']).status == 'CONSUMED'
        assert not db.scalars(select(Permit).where(Permit.task_id == task['id'], Permit.status == 'ACTIVE')).all()
