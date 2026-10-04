"""Refresh-family regressions against real local PostgreSQL and HTTP handlers.

Run with scripts/verify-auth.py; identities and client secrets are ephemeral.
The synchronized race covers SDK pre-validation succeeding in both requests,
then PostgreSQL serializing the two exchanges on the same grant.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import secrets
from threading import Barrier
from urllib.parse import parse_qs, urlparse

import anyio
from fastapi.testclient import TestClient
from mcp.server.auth.provider import TokenError
import pytest
from sqlalchemy import select
from sqlalchemy.engine import make_url

from computeforgood.app import app
from computeforgood.auth import csrf_token, COOKIE
from computeforgood.config import settings
from computeforgood.db import SessionLocal
from computeforgood.models import ApiCredential, OAuthGrant
from computeforgood.oauth_provider import provider
from computeforgood.services import hash_token, now


METHODS = ["none", "client_secret_post", "client_secret_basic"]
REDIRECT = "http://127.0.0.1:34567/replay-callback"


@pytest.fixture
def browser():
    url = make_url(settings.database_url)
    assert url.host in {"127.0.0.1", "localhost"} and url.port in {55471, 55472}
    assert url.database == "cfg" and not settings.demo_mode
    assert settings.oauth_secret_key, "The verifier must supply its ephemeral encryption key"
    suffix = secrets.token_hex(8)
    # Each test has its own limiter identity, preserving every other QA key.
    client = TestClient(app, base_url=settings.public_url, client=("replay-" + suffix, 50000))
    registered = client.post("/api/auth/register", json={
        "username": "replay_" + suffix, "password": "Ephemeral-test-only-" + secrets.token_hex(12),
    })
    assert registered.status_code == 200
    yield client
    client.close()


def register(browser, method):
    response = browser.post("/register", json={
        "client_name": "Refresh replay regression", "redirect_uris": [REDIRECT],
        "token_endpoint_auth_method": method, "scope": "work:read work:write",
    })
    assert response.status_code == 201
    return response.json()


def token_request(browser, info, fields):
    data = {"client_id": info["client_id"], **fields}
    headers = {}
    if info["token_endpoint_auth_method"] == "client_secret_post":
        data["client_secret"] = info["client_secret"]
    elif info["token_endpoint_auth_method"] == "client_secret_basic":
        encoded = base64.b64encode((info["client_id"] + ":" + info["client_secret"]).encode()).decode()
        headers["Authorization"] = "Basic " + encoded
    return browser.post("/token", data=data, headers=headers)


def issue(browser, info):
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    start = browser.get("/authorize", params={
        "client_id": info["client_id"], "response_type": "code", "redirect_uri": REDIRECT,
        "scope": "work:read work:write", "code_challenge": challenge, "code_challenge_method": "S256",
    }, follow_redirects=False)
    assert start.status_code == 302
    grant_id = parse_qs(urlparse(start.headers["location"]).query)["id"][0]
    consent = browser.post("/api/oauth/requests/" + grant_id, json={"approve": True},
                           headers={"X-CSRF-Token": csrf_token(browser.cookies.get(COOKIE))})
    assert consent.status_code == 200
    code = parse_qs(urlparse(consent.json()["redirect_url"]).query)["code"][0]
    result = token_request(browser, info, {
        "grant_type": "authorization_code", "redirect_uri": REDIRECT, "code": code, "code_verifier": verifier,
    })
    assert result.status_code == 200
    return grant_id, result.json()


def refresh(browser, info, token, **extra):
    return token_request(browser, info, {"grant_type": "refresh_token", "refresh_token": token, **extra})


def access_status(browser, tokens):
    return browser.get("/api/me", headers={"Authorization": "Bearer " + tokens["access_token"]}).status_code


def assert_revoked(grant_id):
    # A new independent transaction proves invalid_grant did not roll back
    # revocation in the transaction that detected the replay.
    with SessionLocal() as db:
        assert db.get(OAuthGrant, grant_id).revoked
        credentials = db.scalars(select(ApiCredential).where(ApiCredential.grant_id == grant_id)).all()
        assert credentials and all(row.revoked_at is not None for row in credentials)


@pytest.mark.parametrize("method", METHODS)
def test_rotated_refresh_replay_revokes_live_family_but_not_sibling_grant(browser, method):
    info = register(browser, method)
    grant_id, first = issue(browser, info)
    sibling_id, sibling = issue(browser, info)
    rotated = refresh(browser, info, first["refresh_token"])
    assert rotated.status_code == 200
    fresh = rotated.json()
    assert access_status(browser, first) == 401
    assert access_status(browser, fresh) == 200
    second_rotation = refresh(browser, info, fresh["refresh_token"])
    assert second_rotation.status_code == 200
    assert access_status(browser, fresh) == 401
    fresh = second_rotation.json()
    assert access_status(browser, fresh) == 200
    replay = refresh(browser, info, first["refresh_token"])
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    assert replay.headers["cache-control"] == "no-store"
    assert_revoked(grant_id)
    assert access_status(browser, fresh) == 401
    assert refresh(browser, info, fresh["refresh_token"]).status_code == 400
    # Idempotent repeat and isolation from another consent for the same client.
    assert refresh(browser, info, first["refresh_token"]).status_code == 400
    assert access_status(browser, sibling) == 200
    assert refresh(browser, info, sibling["refresh_token"]).status_code == 200
    with SessionLocal() as db:
        assert not db.get(OAuthGrant, sibling_id).revoked


@pytest.mark.parametrize("method", METHODS)
def test_wrong_client_or_wrong_client_secret_cannot_revoke_rotated_family(browser, method):
    info = register(browser, method)
    outsider = register(browser, method)
    grant_id, first = issue(browser, info)
    fresh = refresh(browser, info, first["refresh_token"]).json()
    response = refresh(browser, outsider, first["refresh_token"])
    assert response.status_code == 400 and response.json()["error"] == "invalid_grant"
    assert refresh(browser, info, "cfg_refresh_unknown_" + secrets.token_hex(24)).status_code == 400
    assert refresh(browser, info, first["access_token"]).status_code == 400
    assert refresh(browser, info, first["refresh_token"], resource="https://untrusted.invalid/mcp").status_code == 400
    if method != "none":
        wrong = {**info, "client_secret": "invalid-client-secret"}
        assert refresh(browser, wrong, first["refresh_token"]).status_code == 401
    with SessionLocal() as db:
        assert not db.get(OAuthGrant, grant_id).revoked
    assert access_status(browser, fresh) == 200
    assert refresh(browser, info, fresh["refresh_token"]).status_code == 200


@pytest.mark.parametrize("method", METHODS)
def test_expired_rotated_token_is_rejected_without_revoking_live_family(browser, method):
    info = register(browser, method)
    grant_id, first = issue(browser, info)
    fresh = refresh(browser, info, first["refresh_token"]).json()
    with SessionLocal.begin() as db:
        row = db.scalar(select(ApiCredential).where(ApiCredential.token_hash == hash_token(first["refresh_token"])))
        row.expires_at = now(db) - timedelta(seconds=1)
    assert refresh(browser, info, first["refresh_token"]).status_code == 400
    with SessionLocal() as db:
        assert not db.get(OAuthGrant, grant_id).revoked
    assert access_status(browser, fresh) == 200
    assert refresh(browser, info, fresh["refresh_token"]).status_code == 200


@pytest.mark.parametrize("method", METHODS)
def test_concurrent_refresh_after_sdk_prevalidation_revokes_winning_family(browser, monkeypatch, method):
    info = register(browser, method)
    grant_id, first = issue(browser, info)
    barrier = Barrier(2)
    original = provider.load_refresh_token

    async def synchronized_load(client, token):
        loaded = await original(client, token)
        if token == first["refresh_token"] and loaded:
            await anyio.to_thread.run_sync(lambda: barrier.wait(timeout=15))
        return loaded

    monkeypatch.setattr(provider, "load_refresh_token", synchronized_load)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda _: refresh(browser, info, first["refresh_token"]), range(2)))
    assert sorted(response.status_code for response in replies) == [200, 400]
    winner = next(response.json() for response in replies if response.status_code == 200)
    loser = next(response.json() for response in replies if response.status_code == 400)
    assert loser["error"] == "invalid_grant"
    assert_revoked(grant_id)
    assert access_status(browser, winner) == 401
    assert refresh(browser, info, winner["refresh_token"]).status_code == 400


def test_invalid_scope_and_stale_provider_calls_preserve_client_and_expiry_boundaries(browser):
    info = register(browser, "none")
    outsider = register(browser, "none")
    grant_id, first = issue(browser, info)
    assert refresh(browser, info, first["refresh_token"], scope="project:plan").status_code == 400
    original_client = anyio.run(provider.get_client, info["client_id"])
    outsider_client = anyio.run(provider.get_client, outsider["client_id"])
    loaded = anyio.run(provider.load_refresh_token, original_client, first["refresh_token"])
    assert loaded
    fresh = refresh(browser, info, first["refresh_token"]).json()
    with pytest.raises(TokenError):
        anyio.run(provider.exchange_refresh_token, outsider_client, loaded, loaded.scopes)
    with SessionLocal.begin() as db:
        row = db.scalar(select(ApiCredential).where(ApiCredential.token_hash == hash_token(first["refresh_token"])))
        row.expires_at = now(db) - timedelta(seconds=1)
    with pytest.raises(TokenError):
        anyio.run(provider.exchange_refresh_token, original_client, loaded, loaded.scopes)
    with SessionLocal() as db:
        assert not db.get(OAuthGrant, grant_id).revoked
    assert access_status(browser, fresh) == 200
    narrowed = refresh(browser, info, fresh["refresh_token"], scope="work:read")
    assert narrowed.status_code == 200 and narrowed.json()["scope"] == "work:read"
