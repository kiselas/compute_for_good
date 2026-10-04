# Deployment and public-launch verification

The local demo runs on `http://127.0.0.1:5180`. It is not a public deployment. Production is a separate Compose project with demo mode disabled and private PostgreSQL/Redis networks.

## Prepare the host

Install Docker Engine and Compose on the chosen host. Point a public DNS hostname at the host and allow TCP 80/443 (UDP 443 optional). Do not expose PostgreSQL, Redis or the backend directly.

On Windows, `scripts/prepare-production.ps1 -PublicHost YOUR_DOMAIN` creates `.env.production` with fresh random database and webhook secrets without printing them. On another OS, copy `deploy/production.env.example` to `.env.production` and replace the placeholder secrets privately. Keep the file outside source control; preserve its database password across redeployments.

Run:

```sh
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml up --build -d --wait
```

`scripts/deploy.ps1` runs the same checks. Compose restart policies recover processes after exit/reboot; a health check alone does not automatically restart an unhealthy container. Use external monitoring and inspect `/api/ready`, which checks both coordination (expiry/outbox) and integration-worker heartbeats. Network retries run separately so a slow GitHub request does not stop lease expiry.

Bootstrap the first operator through `python -m computeforgood.bootstrap_operator --username cfg_operator --output /tmp/operator-login.json` inside the backend container. The CLI generates a random password and writes it only to that file. Copy it immediately to a private host directory with `docker cp` using the backend container ID, then remove the temporary file inside the container. Preserve the private login file outside source control. Do not promote a public account through browser registration or paste passwords into shared logs.

`OAUTH_SECRET_KEY` encrypts confidential MCP-client secrets at rest. Preserve it with the private environment and backups; losing or changing it invalidates registered confidential clients. The preparation script creates a Fernet-compatible key. The server supports public S256 PKCE clients as well as `client_secret_basic` and `client_secret_post` registrations when this key is configured.

## GitHub configuration

Create/configure the GitHub OAuth application with callback `https://YOUR_DOMAIN/api/auth/github/callback`. Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in the private environment. Link contributor accounts before registering real PRs. PR author identity is matched to the authenticated GitHub user ID, not a self-selected local username.

Set a least-privilege `GITHUB_TOKEN` able to read the selected repositories' PRs and checks. Configure repository webhooks using the same private `GITHUB_WEBHOOK_SECRET`, payload URL `https://YOUR_DOMAIN/api/webhooks/github`, JSON content type, and pull_request/check_run/check_suite/status events. Do not expose secrets or commit `.env.production`.

The operator must explicitly configure required CI names on every real verified project. Names may be `check:NAME`, `status:CONTEXT`, or a bare name. A bare name must succeed in every matching check/status source. Missing checks, pending checks and an empty policy do not pass. Reconciliation reads the current GitHub API state rather than trusting webhook arrival order. Failed integrations are visible at `/api/admin/integrations` and can be retried after fixing the cause.

## Before advertising

Verify from outside the server, using the actual public hostname:

- HTTPS certificate and redirects; `/api/ready` returns 200 with database, Redis and worker healthy.
- Clean-browser registration/login/logout; HttpOnly Secure session cookie; mutations reject missing CSRF; no demo identities or fixture catalog in production.
- MCP resource and authorization metadata discover correctly; external client OAuth PKCE and consent succeed; revoked/expired credentials and insufficient scopes fail.
- One real verified project and at least one eligible LOW-risk task are available; intended user can claim and heartbeat.
- A real current-SHA PR completes independent review and maintainer merge; exactly one credit appears. No stale review carries into a new head.
- Mobile landing, navigation, account and connection steps remain usable; empty/error states do not invent success.
- Operator can inspect failed deliveries, pause intake using `REGISTRATION_ENABLED=false`, access backups and restore to a separate database.

Do not mark public readiness from local test results alone. Hosting, DNS, certificates, external MCP-client compatibility and a real GitHub cycle require the target environment.

## Backup and restore

On Windows run `scripts/backup.ps1 -Production`; it uses `pg_dump -Fc` inside the container and `docker cp`, preserving binary data. Store encrypted copies off the host. Production has persistent database, Redis and Caddy certificate volumes; avoid `docker compose down -v`.

Before an upgrade, take a backup. Restore first into a new database to validate the archive, e.g. `createdb -U cfg cfg_restore_check`, followed by `pg_restore -U cfg -d cfg_restore_check /tmp/backup.dump`. Compare table counts and migration revision. A restore over the live database is a separately planned operation with intake stopped and a current backup preserved.

For rollback, use the previous application image and compatible schema; do not run Alembic downgrade blindly after data has been written. Keep the private environment and volume backups separate from source snapshots.

References: [Docker production configuration](https://docs.docker.com/compose/how-tos/production/), [Compose startup dependencies](https://docs.docker.com/compose/how-tos/startup-order/), [GitHub check runs API](https://docs.github.com/en/rest/checks/runs).

## Authentication retention and refresh replay

The coordination worker sweeps up to 200 old records per class every five minutes. Expired GitHub states remain one day, inactive browser sessions thirty days, and inactive credentials ninety days. Refresh tombstones are preserved through their original expiry plus retention and while a token in their family still has an unexpired lifetime. OAuth clients remain persistent. A failed cleanup prevents a fresh coordination heartbeat and retries on the next worker tick. Migration d76394fa81b2 supplies expiry/revocation indexes.

Reusing a matching unexpired rotated refresh revokes that grant's entire access/refresh family and requires a new consent flow. Clients must serialize refresh calls and avoid blindly retrying an already used token. Wrong client/secret/resource and expired unknown tokens do not revoke a different family.

## Encrypted off-host archive

For this shared host, use the existing SSH alias; the tool never transfers a GitHub account token:

```powershell
.\backend\.venv\Scripts\python.exe scripts/backup-remote.py --host nextdish-intl --container compute-for-good-postgres-1 --directory C:/Users/kisel/.codex/private/computeforgood/backups --key C:/Users/kisel/.codex/private/computeforgood/backup-encryption.key
```

The command creates the private key once, verifies PostgreSQL archive magic, encrypts, and checks a decrypted round trip and hashes. Preserve a separate secure copy of the key. To verify recovery, decrypt with Fernet in memory and pipe to `pg_restore --exit-on-error --no-owner` against a newly created isolated database; compare migration revision/counts, then remove only that scratch database. Never restore directly over production during a routine verification.

Manual encrypted snapshot and restore have been checked; a recurring off-host backup schedule and key recovery location are still operator decisions. scripts/backup.ps1 uses unique remote/local filenames and checks the copied checksum; -Project can target an explicit local QA Compose project.
