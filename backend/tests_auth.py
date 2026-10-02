"""Focused authentication checks against the configured PostgreSQL and Redis.

Run only against the local development/test database. Test identities are unique;
no real operator secrets or GitHub credentials are used.
"""
import base64
from datetime import timedelta
import hashlib
import secrets
from concurrent.futures import ThreadPoolExecutor
import pytest
from urllib.parse import parse_qs, urlparse
from fastapi.testclient import TestClient
from sqlalchemy import select
from computeforgood.app import app
from computeforgood.auth import COOKIE, limiter, password_valid
from computeforgood.db import SessionLocal
from computeforgood.models import ApiCredential, BrowserSession, OAuthGrant, User
from computeforgood.config import settings
from computeforgood.services import hash_token, now

pytestmark = pytest.mark.skipif(settings.demo_mode, reason="Run auth suite separately with DEMO_MODE=false")


def account(client):
    username = "authtest_" + secrets.token_hex(5)
    password = "Test-only-long-password-" + secrets.token_hex(8)
    result = client.post("/api/auth/register", json={"username": username, "password": password})
    assert result.status_code == 200
    return result.json(), username, password


def headers(client):
    result = client.get("/api/auth/session")
    assert result.status_code == 200
    return {"X-CSRF-Token": result.json()["csrf_token"]}


def test_browser_credentials_csrf_scope_and_revocation():
    limiter.delete("cfg:auth:register:" + hash_token("testclient"))
    client = TestClient(app, base_url="http://localhost:8010")
    registered, username, password = account(client)
    assert registered["user"]["role"] == "contributor"
    with SessionLocal() as db:
        user = db.get(User, registered["user"]["id"])
        assert password_valid(password, user.password_hash)
        assert user.password_hash != password
    response = client.post("/api/credentials", json={"name": "agent"})
    assert response.status_code == 403
    response = client.post("/api/credentials", headers=headers(client), json={"name": "read only", "scopes": ["work:read"]})
    assert response.status_code == 200
    credential = response.json()
    with SessionLocal() as db:
        assert db.get(ApiCredential, credential["id"]).token_hash == hash_token(credential["token"])
    assert "token" not in client.get("/api/credentials").json()[0]
    bearer = {"Authorization": "Bearer " + credential["token"]}
    assert client.get("/api/me", headers=bearer).status_code == 200
    assert client.post("/api/tasks/does-not-exist/claim", headers=bearer).status_code == 403
    assert client.delete("/api/credentials/" + credential["id"], headers=headers(client)).status_code == 200
    assert client.get("/api/me", headers=bearer).status_code == 401
    session_raw = client.cookies.get(COOKIE)
    assert client.post("/api/auth/logout", headers=headers(client)).status_code == 200
    assert client.get("/api/auth/session").json()["user"] is None
    client.cookies.set(COOKIE, session_raw)
    assert client.get("/api/auth/session").json()["user"] is None
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"username": username, "password": "wrong-password-long"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": username, "password": password}).status_code == 200


def test_expired_session_and_credential_and_untrusted_origin():
    client = TestClient(app, base_url="http://localhost:8010")
    user, _, _ = account(client)
    response = client.post("/api/credentials", headers={**headers(client), "Origin": "https://attacker.invalid"}, json={"name": "evil"})
    assert response.status_code == 403
    response = client.post("/api/credentials", headers=headers(client), json={"name": "expires"})
    assert response.status_code == 200
    credential = response.json()
    with SessionLocal.begin() as db:
        row = db.get(ApiCredential, credential["id"])
        row.expires_at = now(db) - timedelta(seconds=1)
        session = db.scalar(select(BrowserSession).where(BrowserSession.token_hash == hash_token(client.cookies.get(COOKIE))))
        session.expires_at = now(db) - timedelta(seconds=1)
    assert client.get("/api/me", headers={"Authorization": "Bearer " + credential["token"]}).status_code == 401
    assert client.get("/api/auth/session").json()["user"] is None


def test_oauth_pkce_redirect_reuse_refresh_and_revoke():
    client = TestClient(app, base_url="http://localhost:8010")
    account(client)
    metadata = client.get("/.well-known/oauth-authorization-server")
    assert metadata.status_code == 200
    resource = client.get("/.well-known/oauth-protected-resource/mcp")
    assert resource.status_code == 200
    redirect = "http://127.0.0.1:34567/callback"
    registration = client.post("/register", json={"client_name": "Auth test client", "redirect_uris": [redirect], "token_endpoint_auth_method": "none", "scope": "work:read work:write"})
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    params = {"client_id": client_id, "response_type": "code", "redirect_uri": redirect, "scope": "work:read work:write", "code_challenge": challenge, "code_challenge_method": "S256", "state": "test-state"}
    bad = client.get("/authorize", params={**params, "redirect_uri": "https://attacker.invalid/callback"}, follow_redirects=False)
    assert bad.status_code == 400
    start = client.get("/authorize", params=params, follow_redirects=False)
    assert start.status_code == 302
    grant_id = parse_qs(urlparse(start.headers["location"]).query)["id"][0]
    consent = client.post("/api/oauth/requests/" + grant_id, headers=headers(client), json={"approve": True})
    assert consent.status_code == 200
    code = parse_qs(urlparse(consent.json()["redirect_url"]).query)["code"][0]
    exchange = {"grant_type": "authorization_code", "client_id": client_id, "redirect_uri": redirect, "code": code, "code_verifier": verifier}
    assert client.post("/token", data={**exchange, "code_verifier": secrets.token_urlsafe(48)}).status_code == 400
    assert client.post("/token", data={**exchange, "resource": "https://attacker.invalid/mcp"}).status_code == 400
    assert client.post("/token", data={**exchange, "redirect_uri": "http://127.0.0.1:34567/other"}).status_code == 400
    response = client.post("/token", data=exchange)
    assert response.status_code == 200
    tokens = response.json()
    assert client.post("/token", data=exchange).status_code == 400
    bearer = {"Authorization": "Bearer " + tokens["access_token"]}
    assert client.get("/api/me", headers=bearer).status_code == 200
    refreshed = client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert client.get("/api/me", headers=bearer).status_code == 401
    assert client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": tokens["refresh_token"]}).status_code == 400
    fresh = refreshed.json()
    assert client.post("/revoke", data={"client_id": client_id, "token": fresh["access_token"]}).status_code == 200
    assert client.get("/api/me", headers={"Authorization": "Bearer " + fresh["access_token"]}).status_code == 401
    assert client.post("/token", data={"grant_type": "refresh_token", "client_id": client_id, "refresh_token": fresh["refresh_token"]}).status_code == 400


def test_github_oauth_not_configured_and_demo_credentials_disabled():
    client = TestClient(app, base_url="http://localhost:8010")
    assert client.get("/api/auth/github/start", follow_redirects=False).status_code == 503
    assert client.get("/api/auth/github/callback", params={"state": "fake", "code": "fake"}).status_code == 400
    unauthorized = client.get("/mcp/", headers={"Accept": "application/json, text/event-stream"})
    assert unauthorized.status_code == 401
    assert "resource_metadata=" in unauthorized.headers.get("www-authenticate", "")
    assert "/.well-known/oauth-protected-resource/mcp" in unauthorized.headers.get("www-authenticate", "")
    assert client.get("/api/me", headers={"Authorization": "Bearer cfg-demo-alice"}).status_code == 401


def grant(client, client_id, redirect):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    start = client.get("/authorize", params={"client_id": client_id, "response_type": "code", "redirect_uri": redirect, "scope": "work:read work:write", "code_challenge": challenge, "code_challenge_method": "S256", "state": "test"}, follow_redirects=False)
    assert start.status_code == 302
    grant_id = parse_qs(urlparse(start.headers["location"]).query)["id"][0]
    consent = client.post("/api/oauth/requests/" + grant_id, headers=headers(client), json={"approve": True})
    assert consent.status_code == 200
    code = parse_qs(urlparse(consent.json()["redirect_url"]).query)["code"][0]
    return grant_id, {"grant_type": "authorization_code", "client_id": client_id, "redirect_uri": redirect, "code": code, "code_verifier": verifier}


def test_code_expiry_and_atomic_reuse():
    client = TestClient(app, base_url="http://localhost:8010")
    account(client)
    redirect = "http://127.0.0.1:34567/callback"
    registration = client.post("/register", json={"client_name": "Concurrent code test", "redirect_uris": [redirect], "token_endpoint_auth_method": "none", "scope": "work:read work:write"})
    assert registration.status_code == 201
    client_id = registration.json()["client_id"]
    grant_id, exchange = grant(client, client_id, redirect)
    with SessionLocal.begin() as db:
        db.get(OAuthGrant, grant_id).expires_at = now(db) - timedelta(seconds=1)
    assert client.post("/token", data=exchange).status_code == 400
    _, exchange = grant(client, client_id, redirect)
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: client.post("/token", data=exchange).status_code, range(8)))
    assert statuses.count(200) == 1
    assert statuses.count(400) == 7


def test_confidential_client_secret_is_encrypted_and_authenticated():
    if not settings.oauth_secret_key:
        pytest.skip("Set an ephemeral OAUTH_SECRET_KEY to check confidential client registration")
    from computeforgood.models import OAuthClient
    client = TestClient(app, base_url="http://localhost:8010")
    account(client)
    redirect = "http://127.0.0.1:34567/callback"
    registration = client.post("/register", json={"client_name": "Secret post test", "redirect_uris": [redirect], "token_endpoint_auth_method": "client_secret_post", "scope": "work:read work:write"})
    assert registration.status_code == 201
    info = registration.json()
    with SessionLocal() as db:
        stored = db.get(OAuthClient, info["client_id"]).metadata_json
        assert "client_secret" not in stored
        assert info["client_secret"] not in str(stored)
        assert stored.get("_client_secret_ciphertext")
    _, exchange = grant(client, info["client_id"], redirect)
    assert client.post("/token", data=exchange).status_code == 401
    assert client.post("/token", data={**exchange, "client_secret": "wrong-secret"}).status_code == 401
    result = client.post("/token", data={**exchange, "client_secret": info["client_secret"]})
    assert result.status_code == 200


def test_authenticated_stateless_mcp_tools_and_read_only_scope():
    # One SDK transport lifespan per process; the SDK intentionally disallows
    # restarting the same session manager instance.
    with TestClient(app, base_url="http://localhost:8010") as client:
        account(client)
        response = client.post("/api/credentials", headers=headers(client), json={"name": "MCP read-only check", "scopes": ["work:read"]})
        assert response.status_code == 200
        token = response.json()["token"]
        wire_headers = {"Authorization": "Bearer " + token, "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2026-07-28", "mcp-method": "tools/list"}
        meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
        response = client.post("/mcp/", headers=wire_headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": meta}})
        assert response.status_code == 200
        tools = {t["name"] for t in response.json()["result"]["tools"]}
        assert {"checkpoint_work", "get_my_profile", "get_submission_context", "resubmit_submission", "resolve_finding"}.issubset(tools)
        wire_headers.update({"mcp-method": "tools/call", "mcp-name": "get_my_profile"})
        response = client.post("/mcp/", headers=wire_headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"_meta": meta, "name": "get_my_profile", "arguments": {}}})
        assert response.status_code == 200
        assert not response.json()["result"].get("isError")
        wire_headers["mcp-name"] = "claim_work"
        response = client.post("/mcp/", headers=wire_headers, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"_meta": meta, "name": "claim_work", "arguments": {"task_id": "not-a-real-task"}}})
        assert response.status_code == 200
        assert response.json()["result"].get("isError") is True
