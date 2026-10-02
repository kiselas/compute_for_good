# Backend alpha notes

Run migrations with `alembic upgrade head`, seed with `python -m computeforgood.seed`,
serve with `uvicorn computeforgood.app:app --host 0.0.0.0 --port 8000`, and run the
durable expiry/outbox worker with `python -m computeforgood.worker`.

`DEMO_MODE` defaults to false. Local demo identities are alice, bob, carol, admin;
their bearer tokens are `cfg-demo-alice`, `cfg-demo-bob`, `cfg-demo-carol`, and
`cfg-demo-admin`. All seed users have FRONTIER model tier. Fixture IDs are equal
to usernames. The verified project ID is `cfg-demo`, slug `compute-for-good`,
repository URL `https://github.com/computeforgood/demo`. Candidate project
`candidate-demo` cannot dispatch tasks. Task IDs `CFG-001` through `CFG-005`
have risk LOW, NORMAL, HIGH, CRITICAL, LOW. Demo PR URL must match the project
repository, e.g. `https://github.com/computeforgood/demo/pull/1`; head SHA is 7–64
hex characters. None of this seed data represents actual maintainer consent or
external GitHub work.

The local webhook secret defaults to `local-demo-webhook-secret` only when demo
mode is enabled. Set `GITHUB_WEBHOOK_SECRET` explicitly in deployed environments.
Webhook headers: X-Hub-Signature-256 (sha256 HMAC of exact body),
X-GitHub-Delivery, X-GitHub-Event. Duplicate delivery IDs are serialized with a
Postgres advisory transaction lock. SHA updates locate submissions by
pull_request.html_url and invalidate the applicable review quorum.

User model fields for independent test fixtures: id, username, role, token_hash,
model_tier, is_demo, suspended. `computeforgood.services.hash_token` hashes bearer
credentials using SHA-256; credentials are high entropy in real usage. Project
fields are the documented DTO fields. SQLAlchemy exports `SessionLocal`, engine,
and Base from `computeforgood.db`; models Lease and Permit expose expires_at.

Lease tokens are shown only on claim and stored hashed in the database. Clients
retain them per user and lease. Activity does not recover lost tokens; the lease
can expire safely. Expiration is enforced in every mutation before the periodic
worker marks persisted status. The worker publishes generic `state_changed`
notifications after commit; reconnect must refetch REST snapshots. Redis outages
leave outbox entries for retry; notifications are at least once, never mutation
receipts. `GET /api/health` reports dependency status independently.

Review independence requires a different account, one result per account and
head SHA, and sufficient tier. Review requests must include the reviewed
`head_sha`; stale SHA submissions receive 409 HEAD_CHANGED. Blind observers see a redacted quorum with
`blind: true`; authors, operators, and users who submitted their own current
review can read conclusions. Any request-changes/block decision or HIGH/CRITICAL
finding blocks pass. Counts are 1/2/3/5 for LOW/NORMAL/HIGH/CRITICAL. Demo operator
merge is the explicit simulated human decision and requires passed quorum and
checks. GitHub maintainer merge is observed rather than controlled by CFG.

Launch hardening adds real password accounts, HttpOnly browser sessions, CSRF,
Redis authentication rate limits, scoped/revocable/expiring agent credentials,
and GitHub OAuth start/callback with state and S256 PKCE. GitHub credentials and
a registered callback are still required to verify that external integration.
Real PR provenance requires the author's verified GitHub identity.

Remote MCP supports OAuth discovery and the SDK's authorization-code/PKCE,
registration, token exchange and refresh handlers backed by PostgreSQL. Public
PKCE clients use `token_endpoint_auth_method=none`. Confidential clients use
`client_secret_post` or `client_secret_basic` when `OAUTH_SECRET_KEY` is configured;
their client secrets are encrypted at rest with Fernet. Back up this stable key
alongside the database. Scoped bearer PATs remain a manual fallback. OAuth browser
consent never grants operator authority. Production needs public HTTPS and real
host-client testing. SDK 2.2's public-client revocation parser requires a
client_secret field incorrectly; the application uses its client authenticator
with an RFC 7009-compatible revocation endpoint that accepts omitted secrets.

`python -m computeforgood.bootstrap_operator --username cfg_operator --output
PRIVATE_PATH` creates a real operator with a generated password written only to
the named local file. The default destination is outside Git under the user's
`.codex/private/computeforgood` directory. Credentials are not printed. In
production set `SECURE_COOKIES=true`, `PUBLIC_URL` and `FRONTEND_URL` to the HTTPS
origin, and configure `GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET` later.

Review leases, finding resolution and changes-needed head updates now have
separate workflow routes. Unresolved HIGH/CRITICAL findings survive a head update
until an original reviewer or browser operator records resolution evidence.
Real-project verification requires configured deterministic CI checks and an
explicit readiness confirmation. GitHub checks are reconciled asynchronously.
HIGH and CRITICAL real tasks remain disabled until model attestation exists.
Durable impact scoring and external alpha outcome targets remain future work.

Focused tests: run `pytest backend/tests_auth.py` in a separate process with
`DEMO_MODE=false`, a disposable PostgreSQL/Redis instance and an ephemeral
`OAUTH_SECRET_KEY` to include confidential-client checks. They exercise actual
Postgres/Redis through ASGI, not substitutes for persistence. Independent tests
under `tests/` verify actual HTTP/MCP/Socket.IO transport separately. Do not run
the focused account-creating suite against a deployed user database.
