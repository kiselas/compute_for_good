"""Postgres OAuth provider; the official SDK owns protocol validation and PKCE."""
from datetime import timedelta
import re
import secrets
from urllib.parse import urlparse
import anyio
from cryptography.fernet import Fernet
from fastapi import HTTPException
from mcp.server.auth.provider import AccessToken, AuthorizationCode, AuthorizeError, RefreshToken, RegistrationError, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from sqlalchemy import select, update
from .auth import DEFAULT_SCOPES, SCOPES
from .config import settings
from .db import SessionLocal
from .models import ApiCredential, OAuthClient, OAuthGrant, User
from .services import authenticate, hash_token, now


async def database(operation):
    def run():
        # SDK OAuth errors are frozen dataclass exceptions. Python's generator
        # context manager tries to assign their __traceback__ during unwinding,
        # masking invalid_grant as FrozenInstanceError under a concurrent retry.
        # Explicit lifecycle retains the SDK error and rolls back atomically.
        db = SessionLocal()
        try:
            result = operation(db)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    return await anyio.to_thread.run_sync(run)


class PostgresOAuthProvider:
    async def get_client(self, client_id):
        def operation(db):
            row = db.get(OAuthClient, client_id)
            if not row:
                return None
            values = row.metadata_json.copy()
            ciphertext = values.pop("_client_secret_ciphertext", None)
            if ciphertext:
                if not settings.oauth_secret_key:
                    return None
                values["client_secret"] = Fernet(settings.oauth_secret_key.encode()).decrypt(ciphertext.encode()).decode()
            return OAuthClientInformationFull.model_validate(values)
        return await database(operation)

    async def register_client(self, client_info):
        # Public PKCE clients have no client secret to retain. A deployment can
        # provision confidential clients separately when an encrypted secret
        # store is available; this server never persists client secrets in JSON.
        if client_info.token_endpoint_auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
            raise RegistrationError("invalid_client_metadata", "Unsupported client authentication method")
        if client_info.client_secret and not settings.oauth_secret_key:
            raise RegistrationError("invalid_client_metadata", "Public PKCE client required until server OAuth encryption key is configured")
        if not client_info.redirect_uris or len(client_info.redirect_uris) > 10:
            raise RegistrationError("invalid_redirect_uri", "One to ten exact redirect URIs required")
        for uri in client_info.redirect_uris:
            parsed = urlparse(str(uri))
            local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            if parsed.fragment or parsed.username or parsed.password or not parsed.hostname or not (parsed.scheme == "https" or parsed.scheme == "http" and local):
                raise RegistrationError("invalid_redirect_uri", "HTTPS or loopback HTTP redirect URI required; no fragments or userinfo")
        if not set((client_info.scope or "").split()).issubset(SCOPES):
            raise RegistrationError("invalid_client_metadata", "Unsupported scope")
        values = client_info.model_dump(mode="json")
        secret = values.pop("client_secret", None)
        if secret:
            values["_client_secret_ciphertext"] = Fernet(settings.oauth_secret_key.encode()).encrypt(secret.encode()).decode()
        await database(lambda db: db.add(OAuthClient(id=client_info.client_id, metadata_json=values)))

    async def authorize(self, client, params):
        if params.resource and params.resource != settings.public_url + "/mcp":
            raise AuthorizeError("invalid_target", "Unknown protected resource")
        if str(params.redirect_uri) not in [str(uri) for uri in client.redirect_uris or []]:
            raise AuthorizeError("invalid_request", "Redirect URI must exactly match registration")
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", params.code_challenge):
            raise AuthorizeError("invalid_request", "S256 PKCE challenge required")
        values = params.model_dump(mode="json")
        values["resource"] = settings.public_url + "/mcp"
        values["scopes"] = values.get("scopes") or DEFAULT_SCOPES.copy()
        if not set(values["scopes"]).issubset(SCOPES) or "work:read" not in values["scopes"]:
            raise AuthorizeError("invalid_scope", "work:read and optional work:write or project:plan are supported")
        def operation(db):
            grant = OAuthGrant(client_id=client.client_id, params=values, expires_at=now(db) + timedelta(minutes=10))
            db.add(grant)
            db.flush()
            return settings.frontend_url + "/oauth/consent?id=" + grant.id
        return await database(operation)

    async def load_authorization_code(self, client, authorization_code):
        def operation(db):
            row = db.scalar(select(OAuthGrant).where(OAuthGrant.code_hash == hash_token(authorization_code), OAuthGrant.client_id == client.client_id, OAuthGrant.approved.is_(True), OAuthGrant.consumed.is_(False), OAuthGrant.revoked.is_(False), OAuthGrant.expires_at > now(db)))
            if not row:
                return None
            return AuthorizationCode(code=authorization_code, scopes=row.params["scopes"], expires_at=row.expires_at.timestamp(), client_id=client.client_id, code_challenge=row.params["code_challenge"], redirect_uri=row.params["redirect_uri"], redirect_uri_provided_explicitly=row.params["redirect_uri_provided_explicitly"], resource=row.params["resource"], subject=row.user_id)
        return await database(operation)

    def issue(self, db, grant, scopes):
        user = db.get(User, grant.user_id)
        if not user or user.suspended or user.is_demo and not settings.demo_mode:
            raise TokenError("invalid_grant", "Contributor account unavailable")
        access, refresh = "cfg_" + secrets.token_urlsafe(40), "cfg_refresh_" + secrets.token_urlsafe(40)
        for raw, kind, duration in [(access, "access", timedelta(hours=1)), (refresh, "refresh", timedelta(days=30))]:
            db.add(ApiCredential(user_id=user.id, token_hash=hash_token(raw), name="OAuth MCP client", scopes=scopes, client_id=grant.client_id, grant_id=grant.id, kind=kind, expires_at=now(db) + duration))
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=3600, refresh_token=refresh, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client, authorization_code):
        def operation(db):
            row = db.scalar(select(OAuthGrant).where(OAuthGrant.code_hash == hash_token(authorization_code.code)).with_for_update())
            if not row or row.client_id != client.client_id or row.consumed or row.revoked or not row.approved or row.expires_at <= now(db):
                raise TokenError("invalid_grant", "Authorization code expired or already consumed")
            row.consumed = True
            return self.issue(db, row, row.params["scopes"])
        return await database(operation)

    async def load_refresh_token(self, client, refresh_token):
        def operation(db):
            grant, row = self.refresh_family(db, client, refresh_token)
            if not row or not grant or grant.revoked or row.expires_at <= now(db):
                return None
            if row.revoked_at:
                # Rotation leaves a tombstone. A matching, unexpired replay is
                # evidence that this grant's refresh chain may be compromised.
                # Return only after database() commits the family revocation.
                self.revoke_family(db, grant)
                return None
            return RefreshToken(token=refresh_token, client_id=client.client_id, scopes=row.scopes, expires_at=int(row.expires_at.timestamp()), resource=settings.public_url + "/mcp", subject=row.user_id)
        return await database(operation)

    def refresh_family(self, db, client, token):
        candidate = db.scalar(select(ApiCredential).where(
            ApiCredential.token_hash == hash_token(token),
            ApiCredential.client_id == client.client_id,
            ApiCredential.kind == "refresh",
        ))
        if not candidate:
            return None, None
        # Grant-first lock order matches explicit revocation and serializes
        # refreshes across every generation of the same token family.
        grant = db.scalar(select(OAuthGrant).where(
            OAuthGrant.id == candidate.grant_id,
            OAuthGrant.client_id == client.client_id,
        ).with_for_update())
        row = db.scalar(select(ApiCredential).where(ApiCredential.id == candidate.id)
                        .with_for_update().execution_options(populate_existing=True))
        return grant, row

    def revoke_family(self, db, grant):
        grant.revoked = True
        db.execute(update(ApiCredential).where(
            ApiCredential.grant_id == grant.id,
            ApiCredential.revoked_at.is_(None),
        ).values(revoked_at=now(db)))

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        def operation(db):
            grant, row = self.refresh_family(db, client, refresh_token.token)
            if not row or row.expires_at <= now(db) or not set(scopes).issubset(row.scopes):
                raise TokenError("invalid_grant", "Refresh token expired, revoked, or consumed")
            if not grant or grant.revoked:
                raise TokenError("invalid_grant", "Authorization revoked")
            if row.revoked_at:
                # A second exchange may have passed load_refresh_token before
                # the first committed. Persist revocation before raising the
                # SDK exception; raising inside operation would roll it back.
                self.revoke_family(db, grant)
                return None
            db.execute(update(ApiCredential).where(ApiCredential.grant_id == grant.id, ApiCredential.revoked_at.is_(None)).values(revoked_at=now(db)))
            return self.issue(db, grant, scopes)
        result = await database(operation)
        if result is None:
            raise TokenError("invalid_grant", "Refresh token already consumed; authorization revoked")
        return result

    async def load_access_token(self, token):
        def operation(db):
            try:
                user = authenticate(db, token)
            except HTTPException:
                return None
            credential = db.scalar(select(ApiCredential).where(ApiCredential.token_hash == hash_token(token), ApiCredential.kind == "access"))
            return AccessToken(token=token, client_id=credential.client_id or "personal-access-token" if credential else "demo", scopes=user.credential_scopes, expires_at=int(credential.expires_at.timestamp()) if credential else None, resource=settings.public_url + "/mcp", subject=user.id)
        return await database(operation)

    async def verify_token(self, token):
        return await self.load_access_token(token)

    async def revoke_token(self, token):
        def operation(db):
            row = db.scalar(select(ApiCredential).where(ApiCredential.token_hash == hash_token(token.token)))
            if not row:
                return
            if row.grant_id:
                db.scalar(select(OAuthGrant).where(OAuthGrant.id == row.grant_id).with_for_update())
            row = db.scalar(select(ApiCredential).where(ApiCredential.id == row.id).with_for_update().execution_options(populate_existing=True))
            if row.grant_id:
                db.execute(update(ApiCredential).where(ApiCredential.grant_id == row.grant_id).values(revoked_at=now(db)))
                grant = db.get(OAuthGrant, row.grant_id)
                if grant:
                    grant.revoked = True
            else:
                row.revoked_at = now(db)
        await database(operation)


provider = PostgresOAuthProvider()
