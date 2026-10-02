import json
import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone

import httpx
import requests
import socketio
import pytest
from engineio.payload import Payload
from sqlalchemy import insert, select


def public_changes(payload):
    """Validate the public invalidation envelope and expose its individual changes."""
    assert set(payload) == {'event_id', 'kind', 'entity_id', 'changes'}, payload
    assert payload['kind'] == 'state.batch'
    assert payload['entity_id'] == '*'
    assert 1 <= len(payload['changes']) <= 100
    for change in payload['changes']:
        assert set(change) == {'event_id', 'kind', 'entity_id'}, change
        assert all(isinstance(value, str) for value in change.values())
    assert payload['event_id'] == payload['changes'][-1]['event_id']
    return payload['changes']


class RecordingPollingSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.trust_env = False
        self.packet_counts = []

    def request(self, method, url, **kwargs):
        response = super().request(method, url, **kwargs)
        if method == 'GET' and '/socket.io/' in url and response.status_code == 200:
            self.packet_counts.append(len(response.text.split('\x1e')))
        return response


def rpc_json(response, request_id):
    assert response.status_code == 200, response.text
    if response.headers.get('content-type', '').startswith('application/json'):
        payload = response.json()
    else:
        messages = []
        for line in response.text.splitlines():
            if line.startswith('data:'):
                messages.append(json.loads(line[5:].strip()))
        matches = [message for message in messages if message.get('id') == request_id]
        assert matches, f'No JSON-RPC response with id {request_id}: {response.text}'
        payload = matches[-1]
    assert 'error' not in payload, payload
    return payload['result']


def test_actual_mcp_streamable_http_tools_use_shared_domain(api, actors, make_task):
    task = make_task()
    with httpx.Client(base_url=str(api.base_url), timeout=20, follow_redirects=True, trust_env=False) as client:
        headers = {**actors.author.headers, 'Accept': 'application/json, text/event-stream'}
        response = client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'cfg-independent-http-qa', 'version': '1.0'},
            },
        })
        initialized = rpc_json(response, 1)
        assert initialized['serverInfo']['name']
        headers['MCP-Protocol-Version'] = initialized['protocolVersion']
        if response.headers.get('mcp-session-id'):
            headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
        notification = client.post('/mcp', headers=headers,
                                   json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        assert notification.status_code in (200, 202, 204), notification.text
        response = client.post('/mcp', headers=headers,
                               json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        catalog = rpc_json(response, 2)['tools']
        tools = {tool['name']: tool for tool in catalog}
        expected = {'find_work', 'claim_work', 'get_work_context', 'release_work',
                    'prepare_submission', 'register_submission', 'find_review_work', 'submit_review'}
        assert expected <= tools.keys(), tools.keys()

        def call(name, arguments, request_id):
            result = rpc_json(client.post('/mcp', headers=headers, json={
                'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call',
                'params': {'name': name, 'arguments': arguments},
            }), request_id)
            assert result.get('isError', False) is False, result
            return result

        context_fields = tools['get_work_context']['inputSchema'].get('properties', {})
        task_key = next((key for key in ('task_id', 'work_item_id', 'id') if key in context_fields), None)
        assert task_key, context_fields
        context = call('get_work_context', {task_key: task['id']}, 3)
        assert task['id'] in json.dumps(context), context
        claim_fields = tools['claim_work']['inputSchema'].get('properties', {})
        claim_key = next((key for key in ('task_id', 'work_item_id', 'id') if key in claim_fields), None)
        assert claim_key, claim_fields
        claimed = call('claim_work', {claim_key: task['id']}, 4)
        assert task['id'] in json.dumps(claimed), claimed
        state = api.get(f"/api/tasks/{task['id']}", headers=actors.author.headers)
        assert state.status_code == 200, state.text
        assert state.json()['status'] in ('CLAIMED', 'IN_PROGRESS')
        assert state.json()['active_lease']['user_id'] == actors.author.id


def test_actual_mcp_review_claim_heartbeat_release_and_submission(api, actors, make_task):
    from test_http_alpha import submit
    submission = submit(api, make_task(), actors.author)
    with httpx.Client(base_url=str(api.base_url), timeout=20, follow_redirects=True, trust_env=False) as client:
        headers = {**actors.reviewers[0].headers, 'Accept': 'application/json, text/event-stream'}
        response = client.post('/mcp', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
                'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'cfg-independent-review-qa', 'version': '1.0'},
            },
        })
        initialized = rpc_json(response, 1)
        headers['MCP-Protocol-Version'] = initialized['protocolVersion']
        if response.headers.get('mcp-session-id'):
            headers['Mcp-Session-Id'] = response.headers['mcp-session-id']
        client.post('/mcp', headers=headers, json={'jsonrpc': '2.0', 'method': 'notifications/initialized'})

        def call(name, arguments, request_id):
            result = rpc_json(client.post('/mcp', headers=headers, json={
                'jsonrpc': '2.0', 'id': request_id, 'method': 'tools/call',
                'params': {'name': name, 'arguments': arguments},
            }), request_id)
            assert result.get('isError', False) is False, result
            if 'structuredContent' in result:
                return result['structuredContent']
            return json.loads(next(item['text'] for item in result['content'] if item['type'] == 'text'))

        arguments = {'submission_id': submission['id'], 'head_sha': submission['head_sha']}
        first = call('claim_review', arguments, 2)
        refreshed = call('heartbeat_review', {'lease_id': first['id'], 'token': first['token']}, 3)
        assert refreshed['status'] == 'ACTIVE'
        released = call('release_review', {'lease_id': first['id'], 'token': first['token']}, 4)
        assert released['status'] == 'RELEASED'
        second = call('claim_review', arguments, 5)
        result = call('submit_review', {**arguments, 'decision': 'APPROVE',
                                       'summary': 'Independent actual MCP review', 'findings': [],
                                       'review_lease_id': second['id'], 'review_lease_token': second['token']}, 6)
        assert result['submission_id'] == submission['id']
        assert result['head_sha'] == submission['head_sha']
        state = api.get(f"/api/submissions/{submission['id']}", headers=actors.admin.headers).json()
        assert state['quorum']['passed'] is True


def test_socketio_emits_committed_public_change_without_private_token(api, actors, make_task):
    task = make_task()
    received = []
    changed = threading.Event()
    subscribed = threading.Event()
    session = requests.Session()
    session.trust_env = False
    socket = socketio.Client(reconnection=False, logger=False, engineio_logger=False, http_session=session)

    @socket.on('state_changed')
    def on_change(payload):
        received.append(payload)
        subscribed.set()
        if any(change['entity_id'] == task['id'] for change in public_changes(payload)):
            changed.set()

    try:
        socket.connect(str(api.base_url).rstrip('/'), socketio_path='socket.io',
                       transports=['polling'], wait_timeout=10)
        # A namespace connect ACK can precede Redis pub/sub subscription startup.
        # Synchronize on actual delivery, then verify a distinct subsequent claim.
        # Initial delivery is best effort; the product refetches after connection.
        for _ in range(5):
            if subscribed.is_set():
                break
            make_task(title='Socket subscription synchronization fixture')
            subscribed.wait(timeout=1)
        assert subscribed.is_set(), 'Socket namespace connected but public event subscription never became ready'
        response = api.post(f"/api/tasks/{task['id']}/claim", json={}, headers=actors.author.headers)
        assert response.status_code == 200, response.text
        lease = response.json()
        assert changed.wait(timeout=10), f'No committed task change received; events={received}'
        state = api.get(f"/api/tasks/{task['id']}", headers=actors.author.headers).json()
        assert state['active_lease']['id'] == lease['id']
        assert lease['token'] not in json.dumps(received)
        assert actors.author.token not in json.dumps(received)
        for payload in received:
            public_changes(payload)
    finally:
        if socket.connected:
            socket.disconnect()


def test_polling_fallback_survives_more_than_sixteen_persisted_events(api, database):
    assert Payload.max_decode_packets == 16, 'Exercise the default client decoder limit'
    events = database.table('events')
    expected = {str(uuid.uuid4()) for _ in range(40)}
    received = []
    delivered = set()
    ready = threading.Event()
    complete = threading.Event()
    session = RecordingPollingSession()
    socket = socketio.Client(reconnection=False, http_session=session)

    @socket.on('state_changed')
    def on_change(payload):
        received.append(payload)
        delivered.update(change['event_id'] for change in public_changes(payload))
        ready.set()
        if expected <= delivered:
            complete.set()

    def persist(ids):
        with database.engine.begin() as connection:
            connection.execute(insert(events), [dict(
                id=event_id, kind='qa.socket_burst', entity_id=event_id,
                message='Isolated QA public invalidation burst', published=False,
                created_at=datetime.now(timezone.utc),
            ) for event_id in ids])

    try:
        socket.connect(str(api.base_url).rstrip('/'), transports=['polling'], wait_timeout=10)
        persist([str(uuid.uuid4())])
        assert ready.wait(5), 'Subscriber did not receive readiness event'
        persist(expected)  # All forty events commit together before dispatch can observe them.
        assert complete.wait(10), f'Burst incomplete: {len(expected & delivered)}/40'
        assert socket.connected, 'Default polling decoder disconnected during the event burst'
        assert max(session.packet_counts) <= Payload.max_decode_packets
        assert any(len(expected & {item['event_id'] for item in p['changes']}) > 16 for p in received)
        deadline = time.monotonic() + 5
        while True:
            with database.engine.connect() as connection:
                snapshot = connection.execute(select(events.c.id, events.c.published).where(events.c.id.in_(expected))).all()
            if all(row.published for row in snapshot) or time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        assert len(snapshot) == 40 and all(row.published for row in snapshot)
    finally:
        if socket.connected:
            socket.disconnect()


@pytest.mark.skipif(not os.getenv('CFG_PRODUCTION_BASE_URL'), reason='Separate production proxy stack required')
def test_actual_websocket_through_caddy_and_nginx_committed_public_change():
    url = os.environ['CFG_PRODUCTION_BASE_URL']
    assert url.startswith(('http://127.0.0.1:', 'http://localhost:')), 'Local-only account fixture'
    received = []
    changed = threading.Event()
    target = {'id': None}
    session = requests.Session()
    session.trust_env = False
    socket = socketio.Client(reconnection=False, http_session=session,
                             websocket_extra_options={'http_no_proxy': ['127.0.0.1', 'localhost']})

    @socket.on('state_changed')
    def on_change(payload):
        received.append(payload)
        if any(item['entity_id'] == target['id'] for item in public_changes(payload)):
            changed.set()

    with httpx.Client(base_url=url, timeout=20, trust_env=False) as client:
        assert client.get('/api/health').json()['demo_mode'] is False
        csrf = None
        password = secrets.token_urlsafe(32)
        try:
            socket.connect(url, transports=['websocket'], wait_timeout=10)
            assert socket.transport() == 'websocket'
            response = client.post('/api/auth/register', json={
                'username': 'socket_smoke_' + secrets.token_hex(6), 'password': password,
            })
            assert response.status_code == 200, response.text
            account = response.json()
            target['id'] = account['user']['id']
            csrf = account['csrf_token']
            # Also account for an event arriving between register and response parsing.
            if any(item['entity_id'] == target['id'] for p in received for item in p['changes']):
                changed.set()
            assert changed.wait(10), 'No committed registration event through WebSocket proxy'
            assert client.get('/api/me').json()['id'] == target['id']
            assert password not in json.dumps(received)
            assert csrf not in json.dumps(received)
        finally:
            if csrf:
                client.post('/api/auth/logout', headers={'X-CSRF-Token': csrf})
            if socket.connected:
                socket.disconnect()
