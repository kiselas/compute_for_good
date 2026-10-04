"""Browser accounts, CSRF-protected sessions, and scoped agent credentials."""
import base64
from datetime import timedelta
import hashlib
import hmac
import secrets
from urllib.parse import parse_qs, urlencode
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select, update
from .config import settings
from .db import SessionLocal
from .models import ApiCredential, BrowserSession, GitHubLoginState, OAuthClient, OAuthGrant, User
from .services import event, hash_token, now

DEFAULT_SCOPES = ["work:read", "work:write"]
SCOPES = DEFAULT_SCOPES + ["project:plan"]
COOKIE = "cfg_session"
router = APIRouter()
limiter = Redis.from_url(settings.redis_url, socket_timeout=2, socket_connect_timeout=2)


class OAuthRequestGuard(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path not in {"/register", "/token", "/authorize", "/revoke"}:
            return await call_next(request)
        try:
            rate_limit(request, "oauth-" + request.url.path.strip("/"), 120 if request.url.path in {"/token", "/revoke"} else 30)
        except HTTPException as error:
            return JSONResponse({"error": "temporarily_unavailable", "error_description": error.detail}, status_code=error.status_code, headers=error.headers)
        if request.method == "POST":
            raw = await request.body()
            if len(raw) > 65536:
                return JSONResponse({"error": "invalid_request"}, status_code=413)
            if request.url.path == "/token":
                try:
                    values = parse_qs(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    return JSONResponse({"error": "invalid_request"}, status_code=400)
                resources = values.get("resource", [])
                if resources and (len(resources) != 1 or resources[0] != settings.public_url + "/mcp"):
                    return JSONResponse({"error": "invalid_target"}, status_code=400, headers={"Cache-Control": "no-store"})
        return await call_next(request)


@router.post("/revoke")
async def revoke_oauth(request: Request):
    # SDK 2.2's RevocationRequest incorrectly requires a client_secret form field
    # even for public clients. Keep its client authenticator and provider while
    # accepting the RFC 7009 public-client request without that field.
    from mcp.server.auth.middleware.client_auth import AuthenticationError, ClientAuthenticator
    from .oauth_provider import provider
    try:
        client = await ClientAuthenticator(provider).authenticate_request(request)
    except AuthenticationError:
        return JSONResponse({"error": "invalid_client"}, status_code=401)
    form = await request.form()
    token_value = form.get("token")
    if not isinstance(token_value, str) or not token_value:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    access = await provider.load_access_token(token_value)
    token = access or await provider.load_refresh_token(client, token_value)
    if token and token.client_id == client.client_id:
        await provider.revoke_token(token)
    return Response(status_code=200, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


def password_hash(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=32768, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=64)
    return "scrypt$32768$8$1$" + salt.hex() + "$" + digest.hex()


def password_valid(password, encoded):
    try:
        algorithm, n, r, p, salt, expected = encoded.split("$")
        if algorithm != "scrypt" or (int(n), int(r), int(p)) != (32768, 8, 1):
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=64)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError, AttributeError):
        return False


_DUMMY_HASH = password_hash(secrets.token_urlsafe(32))


def db_session():
    with SessionLocal.begin() as db:
        yield db


def user_dto(user):
    return {"id": user.id, "username": user.username, "role": user.role,
            "github_connected": bool(user.github_id)}


def csrf_token(raw):
    return hmac.new(raw.encode(), b"cfg-browser-csrf-v1", hashlib.sha256).hexdigest()


def check_origin(request):
    origin = request.headers.get("origin")
    allowed = {*settings.cors_origins, settings.public_url, settings.frontend_url}
    if origin and origin not in allowed:
        raise HTTPException(403, "Untrusted browser origin")


def rate_limit(request, namespace, limit=15):
    # Use the socket peer, never untrusted forwarding headers. Reverse proxy can
    # additionally enforce a real-IP limit before forwarding to this service.
    peer = request.client.host if request.client else "unknown"
    key = "cfg:auth:" + namespace + ":" + hash_token(peer)
    try:
        result = limiter.eval("local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],600) end; return n", 1, key)
    except Exception:
        raise HTTPException(503, "Authentication rate limiter unavailable")
    if result > limit:
        raise HTTPException(429, "Too many authentication attempts; retry later", headers={"Retry-After": "600"})


def resolve_cookie(request, db, require=False):
    raw = request.cookies.get(COOKIE)
    if not raw:
        if require:
            raise HTTPException(401, "Browser login required")
        return None
    session = db.scalar(select(BrowserSession).where(BrowserSession.token_hash == hash_token(raw), BrowserSession.revoked_at.is_(None), BrowserSession.expires_at > now(db)))
    user = db.get(User, session.user_id) if session else None
    if not user or user.suspended or user.is_demo and not settings.demo_mode:
        if require:
            raise HTTPException(401, "Browser session expired or revoked")
        return None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        check_origin(request)
        received = request.headers.get("X-CSRF-Token", "")
        if not hmac.compare_digest(received.encode(), csrf_token(raw).encode()):
            raise HTTPException(403, "CSRF token required")
    request.state.browser_session = session
    return user


def browser_user(request: Request, db=Depends(db_session, scope="function")):
    return resolve_cookie(request, db, True)


def session_response(db, user, response):
    raw = secrets.token_urlsafe(48)
    db.add(BrowserSession(user_id=user.id, token_hash=hash_token(raw), expires_at=now(db) + timedelta(days=7)))
    response.set_cookie(COOKIE, raw, max_age=7 * 86400, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/")
    response.headers["Cache-Control"] = "no-store"
    return {"user": user_dto(user), "csrf_token": csrf_token(raw)}


class AccountBody(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{2,39}$")
    password: str = Field(min_length=12, max_length=256)


@router.post("/api/auth/register")
def register(body: AccountBody, request: Request, response: Response, db=Depends(db_session, scope="function")):
    if not settings.registration_enabled:
        raise HTTPException(403, "Registration disabled")
    check_origin(request)
    rate_limit(request, "register", 10)
    username = body.username.lower()
    if db.scalar(select(User.id).where(User.username == username)):
        raise HTTPException(409, "Username unavailable")
    user = User(username=username, password_hash=password_hash(body.password), token_hash=hash_token(secrets.token_urlsafe(48)), model_tier="STRONG", role="contributor", is_demo=False)
    db.add(user)
    db.flush()
    event(db, "account.registered", user.id, "Contributor account created", user.id)
    return session_response(db, user, response)


@router.post("/api/auth/login")
def login(body: AccountBody, request: Request, response: Response, db=Depends(db_session, scope="function")):
    check_origin(request)
    rate_limit(request, "login")
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    valid = password_valid(body.password, user.password_hash if user and user.password_hash else _DUMMY_HASH)
    if not valid or not user or user.suspended or user.is_demo:
        raise HTTPException(401, "Invalid username or password")
    old = request.cookies.get(COOKIE)
    if old:
        db.execute(update(BrowserSession).where(BrowserSession.token_hash == hash_token(old)).values(revoked_at=now(db)))
    return session_response(db, user, response)


@router.get("/api/auth/session")
def session(request: Request, response: Response, db=Depends(db_session, scope="function")):
    response.headers["Cache-Control"] = "no-store"
    user = resolve_cookie(request, db)
    return {"user": user_dto(user) if user else None, "csrf_token": csrf_token(request.cookies[COOKIE]) if user else None, "github_available": bool(settings.github_client_id and settings.github_client_secret)}


@router.post("/api/auth/logout")
def logout(request: Request, response: Response, user=Depends(browser_user), db=Depends(db_session, scope="function")):
    db.execute(update(BrowserSession).where(BrowserSession.id == request.state.browser_session.id).values(revoked_at=now(db)))
    response.delete_cookie(COOKIE, path="/", secure=settings.secure_cookies, httponly=True, samesite="lax")
    return {"logged_out": True}


def credential_dto(row):
    return {key: getattr(row, key) for key in ("id", "name", "scopes", "expires_at", "created_at", "revoked_at")}


class CredentialBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    scopes: list[str] = Field(default_factory=lambda: DEFAULT_SCOPES.copy(), min_length=1, max_length=3)
    expires_in_days: int = Field(default=30, ge=1, le=90)


@router.get("/api/credentials")
def credentials(user=Depends(browser_user), db=Depends(db_session, scope="function")):
    return [credential_dto(row) for row in db.scalars(select(ApiCredential).where(ApiCredential.user_id == user.id, ApiCredential.kind == "access").order_by(ApiCredential.created_at.desc()))]


@router.post("/api/credentials")
def create_credential(body: CredentialBody, response: Response, user=Depends(browser_user), db=Depends(db_session, scope="function")):
    if not set(body.scopes).issubset(SCOPES):
        raise HTTPException(422, "Unknown credential scope")
    active = db.scalars(select(ApiCredential.id).where(ApiCredential.user_id == user.id, ApiCredential.revoked_at.is_(None), ApiCredential.expires_at > now(db))).all()
    if len(active) >= 20:
        raise HTTPException(409, "Revoke an existing credential before creating another")
    raw = "cfg_" + secrets.token_urlsafe(40)
    row = ApiCredential(user_id=user.id, token_hash=hash_token(raw), name=body.name, scopes=sorted(set(body.scopes)), expires_at=now(db) + timedelta(days=body.expires_in_days))
    db.add(row)
    db.flush()
    response.headers["Cache-Control"] = "no-store"
    event(db, "credential.created", row.id, "Contributor created an agent credential", user.id)
    return {**credential_dto(row), "token": raw}


@router.delete("/api/credentials/{credential_id}")
def revoke_credential(credential_id: str, user=Depends(browser_user), db=Depends(db_session, scope="function")):
    row = db.scalar(select(ApiCredential).where(ApiCredential.id == credential_id, ApiCredential.user_id == user.id))
    if not row:
        raise HTTPException(404, "Credential not found")
    if row.grant_id:
        db.scalar(select(OAuthGrant).where(OAuthGrant.id == row.grant_id).with_for_update())
    row = db.scalar(select(ApiCredential).where(ApiCredential.id == credential_id).with_for_update().execution_options(populate_existing=True))
    timestamp = now(db)
    if row.grant_id:
        db.execute(update(ApiCredential).where(ApiCredential.grant_id == row.grant_id).values(revoked_at=timestamp))
        grant = db.get(OAuthGrant, row.grant_id)
        if grant:
            grant.revoked = True
    else:
        row.revoked_at = timestamp
    event(db, "credential.revoked", row.id, "Contributor revoked an agent credential", user.id)
    return {"revoked": True}


class ConsentBody(BaseModel):
    approve: bool


@router.get("/api/oauth/requests/{grant_id}")
def consent_info(grant_id: str, user=Depends(browser_user), db=Depends(db_session, scope="function")):
    grant = db.get(OAuthGrant, grant_id)
    if not grant or grant.expires_at <= now(db) or grant.approved or grant.revoked:
        raise HTTPException(404, "Authorization request expired")
    client = db.get(OAuthClient, grant.client_id)
    return {"client_name": client.metadata_json.get("client_name") or "Unnamed MCP client", "scopes": grant.params["scopes"], "redirect_uri": grant.params["redirect_uri"]}


@router.post("/api/oauth/requests/{grant_id}")
def consent(grant_id: str, body: ConsentBody, user=Depends(browser_user), db=Depends(db_session, scope="function")):
    grant = db.scalar(select(OAuthGrant).where(OAuthGrant.id == grant_id).with_for_update())
    if not grant or grant.expires_at <= now(db) or grant.approved or grant.revoked:
        raise HTTPException(409, "Authorization request expired or already used")
    from mcp.server.auth.handlers.authorize import construct_redirect_uri
    params = grant.params
    if not body.approve:
        grant.revoked = True
        return {"redirect_url": construct_redirect_uri(params["redirect_uri"], error="access_denied", **({"state": params["state"]} if params.get("state") else {}))}
    raw = secrets.token_urlsafe(40)
    grant.approved = True
    grant.user_id = user.id
    grant.code_hash = hash_token(raw)
    grant.expires_at = now(db) + timedelta(minutes=5)
    values = {"code": raw, "iss": settings.public_url + "/"}
    if params.get("state"):
        values["state"] = params["state"]
    return {"redirect_url": construct_redirect_uri(params["redirect_uri"], **values)}


@router.get("/api/auth/github/start")
def github_start(request: Request, db=Depends(db_session, scope="function")):
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(503, "GitHub OAuth is not configured yet")
    user = resolve_cookie(request, db)
    state, cookie, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    db.add(GitHubLoginState(id=state, cookie_hash=hash_token(cookie), verifier=verifier, user_id=user.id if user else None, expires_at=now(db) + timedelta(minutes=10)))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    query = {"client_id": settings.github_client_id, "redirect_uri": settings.public_url + "/api/auth/github/callback", "state": state, "scope": "read:user", "code_challenge": challenge, "code_challenge_method": "S256"}
    response = RedirectResponse("https://github.com/login/oauth/authorize?" + urlencode(query), status_code=302)
    response.set_cookie("cfg_github_state", cookie, httponly=True, secure=settings.secure_cookies, samesite="lax", max_age=600, path="/api/auth/github")
    return response


@router.get("/api/auth/github/callback")
def github_callback(request: Request, state: str, code: str, db=Depends(db_session, scope="function")):
    record = db.scalar(select(GitHubLoginState).where(GitHubLoginState.id == state).with_for_update())
    cookie = request.cookies.get("cfg_github_state", "")
    if not record or record.consumed or record.expires_at <= now(db) or not hmac.compare_digest(record.cookie_hash, hash_token(cookie)):
        raise HTTPException(400, "Invalid GitHub OAuth state")
    current = resolve_cookie(request, db)
    if record.user_id and (not current or current.id != record.user_id):
        raise HTTPException(403, "Sign in to the account that started GitHub connection")
    try:
        response = httpx.post("https://github.com/login/oauth/access_token", data={"client_id": settings.github_client_id, "client_secret": settings.github_client_secret, "code": code, "redirect_uri": settings.public_url + "/api/auth/github/callback", "code_verifier": record.verifier}, headers={"Accept": "application/json"}, timeout=12)
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise ValueError
        profile_response = httpx.get("https://api.github.com/user", headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}, timeout=12)
        profile_response.raise_for_status()
        profile = profile_response.json()
        identity = str(profile["id"])
    except (httpx.HTTPError, ValueError, KeyError):
        raise HTTPException(502, "GitHub login failed; start again")
    existing = db.scalar(select(User).where(User.github_id == identity))
    if record.user_id:
        user = db.get(User, record.user_id)
        if existing and existing.id != user.id:
            raise HTTPException(409, "GitHub identity is already linked to another account")
        user.github_id = identity
    elif existing:
        user = existing
    else:
        if not settings.registration_enabled:
            raise HTTPException(403, "Registration disabled")
        username = profile["login"].lower()
        if db.scalar(select(User.id).where(User.username == username)):
            username = username[:28] + "_" + secrets.token_hex(4)
        user = User(username=username, github_id=identity, role="contributor", model_tier="STRONG", token_hash=hash_token(secrets.token_urlsafe(48)), is_demo=False)
        db.add(user)
        db.flush()
    if user.suspended or user.is_demo:
        raise HTTPException(403, "Account disabled")
    record.consumed = True
    result = RedirectResponse(settings.frontend_url + "/connect", status_code=302)
    session_response(db, user, result)
    result.delete_cookie("cfg_github_state", path="/api/auth/github")
    event(db, "account.github_connected", user.id, "GitHub identity verified", user.id)
    return result
