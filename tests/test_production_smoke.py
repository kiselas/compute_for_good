"""Actual HTTP checks against the separate demo-free deployment stack.

Enable with CFG_PRODUCTION_BASE_URL; never inserts fixture projects or PRs.
"""
import base64
import hashlib
import os
import secrets
from urllib.parse import parse_qs, urlparse
import httpx
import pytest

pytestmark = pytest.mark.skipif(not os.getenv('CFG_PRODUCTION_BASE_URL'), reason='Separate production-mode stack required')


@pytest.fixture(scope='module')
def production():
    url = os.environ['CFG_PRODUCTION_BASE_URL']
    assert url.startswith(('http://127.0.0.1:', 'http://localhost:')), 'This account-creating smoke suite is local-only'
    with httpx.Client(base_url=url, timeout=20, trust_env=False) as client:
        assert client.get('/api/health').json()['demo_mode'] is False
        response = client.post('/api/auth/register', json={'username': 'smoke_' + secrets.token_hex(6), 'password': secrets.token_urlsafe(32)})
        assert response.status_code == 200
        yield client, response.json()['csrf_token']
        client.post('/api/auth/logout', headers={'X-CSRF-Token': response.json()['csrf_token']})


def test_production_readiness_and_fixture_exclusion(production):
    client, _ = production
    assert client.get('/api/ready').status_code == 200
    assert client.get('/api/demo/users').status_code == 404
    assert client.get('/api/me', headers={'Authorization': 'Bearer cfg-demo-admin'}).status_code == 401
    catalog = client.get('/api/projects').json()
    assert all(not p['is_demo'] for p in catalog)
    assert client.get('/api/admin/operations').status_code == 403


def test_production_cookie_csrf_and_mcp_personal_credential(production):
    client, csrf = production
    assert client.post('/api/credentials', json={'name': 'missing csrf'}).status_code == 403
    result = client.post('/api/credentials', headers={'X-CSRF-Token': csrf}, json={'name': 'Local smoke', 'scopes': ['work:read'], 'expires_in_days': 1})
    assert result.status_code in (200, 201)
    credential = result.json()
    headers = {'Authorization': 'Bearer ' + credential['token'], 'Accept': 'application/json, text/event-stream'}
    initialized = client.post('/mcp/', headers=headers, json={'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'production-http-smoke', 'version': '1'}}})
    assert initialized.status_code == 200
    response = client.get('/api/credentials')
    assert credential['token'] not in response.text
    assert client.post('/api/tasks/no-task/claim', headers=headers, json={}).status_code == 403
    assert client.delete('/api/credentials/' + credential['id'], headers={'X-CSRF-Token': csrf}).status_code == 200
    assert client.post('/mcp/', headers=headers, json={'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}).status_code == 401


@pytest.mark.parametrize('method', ['none', 'client_secret_post', 'client_secret_basic'])
def test_production_oauth_pkce_discovery_and_revocation(production, method):
    client, csrf = production
    challenge_response = client.post('/mcp/', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert challenge_response.status_code == 401
    assert 'resource_metadata=' in challenge_response.headers['www-authenticate']
    metadata = client.get('/.well-known/oauth-authorization-server').json()
    assert 'S256' in metadata['code_challenge_methods_supported']
    resource = str(client.base_url).rstrip('/') + '/mcp'
    redirect = 'http://127.0.0.1:8099/callback'
    registration = client.post('/register', json={'redirect_uris': [redirect], 'client_name': 'Local MCP smoke', 'token_endpoint_auth_method': method, 'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'], 'scope': 'work:read work:write'})
    assert registration.status_code == 201
    identity = registration.json()
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    authorization = client.get('/authorize', params={'client_id': identity['client_id'], 'redirect_uri': redirect, 'response_type': 'code', 'code_challenge': challenge, 'code_challenge_method': 'S256', 'scope': 'work:read', 'state': 'smoke-state', 'resource': resource})
    assert authorization.status_code in (302, 303, 307)
    grant = parse_qs(urlparse(authorization.headers['location']).query)['id'][0]
    consent = client.post('/api/oauth/requests/' + grant, json={'approve': True}, headers={'X-CSRF-Token': csrf})
    assert consent.status_code == 200
    callback = parse_qs(urlparse(consent.json()['redirect_url']).query)
    assert callback['state'] == ['smoke-state']
    data = {'grant_type': 'authorization_code', 'client_id': identity['client_id'], 'code': callback['code'][0], 'redirect_uri': redirect, 'code_verifier': verifier, 'resource': resource}
    authentication = None
    if method == 'client_secret_post':
        data['client_secret'] = identity['client_secret']
    elif method == 'client_secret_basic':
        authentication = (identity['client_id'], identity['client_secret'])
    token_response = client.post('/token', data=data, auth=authentication)
    assert token_response.status_code == 200
    access = token_response.json()['access_token']
    assert client.get('/api/me', headers={'Authorization': 'Bearer ' + access}).status_code == 200
    assert client.post('/token', data=data, auth=authentication).status_code == 400
    revoke = {'client_id': identity['client_id'], 'token': access, 'token_type_hint': 'access_token'}
    if method == 'client_secret_post':
        revoke['client_secret'] = identity['client_secret']
    assert client.post('/revoke', data=revoke, auth=authentication).status_code == 200
    assert client.get('/api/me', headers={'Authorization': 'Bearer ' + access}).status_code == 401
