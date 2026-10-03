# GitHub CI and shared-server deployment

The source repository is `kiselas/compute_for_good`. The `Launch verification` workflow runs on pushes, pull requests and manual requests with read-only repository permissions. The frontend job runs locked `npm ci`, checks all three language catalogs, TypeScript and the production build. The integration job starts actual PostgreSQL and Redis, API and both workers, plus an independent demo-free Caddy/nginx stack. It executes the integration suite and real-storage authentication tests. `CFG_PRODUCTION_BASE_URL` is mandatory in CI; the XML check requires all six production checks, including WebSocket through both proxies, and rejects any skipped test. Test evidence is retained for 14 days.

Only ephemeral runner databases receive fixture accounts. Production-smoke secure cookies are disabled exclusively on runner loopback; public deployment uses secure cookies and its HTTPS origin. Runner cleanup may delete its own isolated volumes and does not operate on the target server.

`Deploy production` runs after a successful **push** verification on `main` in the same repository. PR runs, forks and other branches cannot trigger deployment. A manual deployment accepts a full lowercase 40-character SHA, also requiring successful push verification and equality with the current `main` head. This is checked before checkout and again before SSH so an outdated run cannot replace a newer release. The manual workflow must itself be selected from `main`.

The runner builds `linux/amd64` images and publishes:

- `ghcr.io/kiselas/compute-for-good-backend:<sha>` — API and both workers.
- `ghcr.io/kiselas/compute-for-good-frontend:<sha>` — built React assets and nginx.

Existing SHA-tagged images are reused when rerunning deployment; the workflow does not deliberately overwrite them or use a `latest` tag. Actions are pinned to full commit IDs. Production deployment is serialized, and a deployment already running is not canceled by a subsequent push.

## Deployment connection contract

The `production` GitHub environment or repository must provide these secrets:

| Secret | Value |
|---|---|
| `CFG_DEPLOY_HOST` | `185.115.33.169` |
| `CFG_DEPLOY_USER` | `root`, with a dedicated forced-command key matching the host's existing SSH policy |
| `CFG_DEPLOY_KEY` | Private key for that account's forced-command authorization |
| `CFG_DEPLOY_KNOWN_HOSTS` | Verified server SSH host-key record; never use a blind runtime keyscan |

The sole SSH command is `/opt/compute-for-good/bin/deploy-release <sha>`. Standard input contains exactly two newline-terminated lines: `GITHUB_ACTOR`, then this job's `GITHUB_TOKEN`. The deployment script reads them without printing, performs `docker login ghcr.io --password-stdin` using a temporary private `DOCKER_CONFIG`, pulls both SHA-tagged images, and removes the temporary registry credentials on exit. No registry credential is stored permanently on the server; the job token expires after the run. The workflow grants `packages: write` for publication and `contents: read` / `actions: read` for provenance checks. Package source labels associate the images with this repository. Public package visibility is optional and does not gate deployment.

The dedicated authorized key denies shell access, PTY and forwarding, and accepts only the exact release command with a validated 40-character SHA. The host script is owned by the administrator; this key cannot invoke arbitrary commands to rewrite it. Application secrets remain in the server's private environment file and are not passed through Actions. Database, Redis, volumes and neighbor services are not replaced by GitHub secrets.

The server release procedure is responsible for serialized deployment, backup before migrations, pulling the release, upgrading the schema, replacing API/workers/frontend and checking `/api/ready`. Database migrations are not automatically reversed; image rollback requires schema compatibility. The shared VPN/Content Factory edge and its certificate routing are managed separately from application release images. Consult [shared-server-deployment.md](shared-server-deployment.md) for exact routes, readiness and recovery.

## Verification evidence

A checked-in workflow is not evidence of a working hosted deployment. Confirm the actual `Launch verification` run, its XML results, both published SHA tags, the `Deploy production` run and the server's release/readiness before advertising. DNS and TLS activation are separate steps; CI's local proxy smoke does not prove the public domain or a real GitHub repository integration works.

GitHub documents the elevated privileges of `workflow_run` and the need to restrict trusted checkouts in its [workflow event reference](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows) and [secure use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
